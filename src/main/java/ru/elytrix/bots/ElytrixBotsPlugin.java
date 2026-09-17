package ru.elytrix.bots;

import dev.by1337.virtualentity.api.virtual.player.VirtualPlayer;
import net.luckperms.api.LuckPerms;
import net.luckperms.api.LuckPermsProvider;
import net.luckperms.api.node.types.InheritanceNode;
import net.kyori.adventure.text.serializer.legacy.LegacyComponentSerializer;
import org.bukkit.*;
import org.bukkit.block.Block;
import org.bukkit.configuration.ConfigurationSection;
import org.bukkit.configuration.file.YamlConfiguration;
import org.bukkit.command.*;
import org.bukkit.entity.Player;
import org.bukkit.event.*;
import org.bukkit.event.player.*;
import org.bukkit.event.server.ServerListPingEvent;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.scheduler.BukkitTask;
import org.bukkit.util.BoundingBox;
import org.by1337.blib.geom.Vec3d;

import java.io.File;
import java.util.*;

public final class ElytrixBotsPlugin extends JavaPlugin implements Listener, CommandExecutor, TabCompleter {
    private final List<VirtualPlayer> tabBots = new ArrayList<>();
    private final List<MovingBot> liveBots = new ArrayList<>();
    private BukkitTask ticker;
    private YamlConfiguration bots;
    private DatasetManager datasets;
    private final Random random = new Random();
    private final BotTeamManager teams = new BotTeamManager();
    private final NmsFakePlayerRegistry registry = new NmsFakePlayerRegistry();
    private ProxySyncSender proxySync;
    private PopulationDatabase database;
    private final Map<String,ActiveBot> active = new LinkedHashMap<>();
    private final List<BotProfile> profiles = new ArrayList<>();
    private long nextPopulationChange;
    private int dailyMinuteJitter;
    private double visibleChance;

    @Override public void onEnable() {
        saveDefaultConfig(); saveResource("bots.yml", false);
        bots = YamlConfiguration.loadConfiguration(new File(getDataFolder(), "bots.yml"));
        datasets = new DatasetManager(this);
        ensureProfiles();
        database = new PopulationDatabase(new File(getDataFolder(), "population.db"));
        dailyMinuteJitter=random.nextInt(91)-45;
        double visibleMin=getConfig().getDouble("population.visible-percent.min",20)/100D,visibleMax=getConfig().getDouble("population.visible-percent.max",60)/100D;visibleChance=visibleMin+random.nextDouble()*Math.max(0,visibleMax-visibleMin);
        nextPopulationChange=System.currentTimeMillis()+getConfig().getLong("population.first-join-delay-seconds",15)*1000L;
        Bukkit.getPluginManager().registerEvents(this, this);
        proxySync=new ProxySyncSender(this,this::fakeCount); proxySync.start();
        PluginCommand botCommand=Objects.requireNonNull(getCommand("elytrixbots"));botCommand.setExecutor(this);botCommand.setTabCompleter(this);
        int period = Math.max(1, getConfig().getInt("settings.movement-period-ticks", 2));
        ticker = Bukkit.getScheduler().runTaskTimer(this, () -> tick(period), 1L, period);
        getLogger().info("Loaded " + tabBots.size() + " TAB and " + liveBots.size() + " live bots.");
    }

    @Override public void onDisable() {
        if (ticker != null) ticker.cancel();
        if (proxySync != null) proxySync.stop();
        for (Player viewer : realPlayers()) {
            tabBots.forEach(bot -> bot.sendRemovePlayerPacket(viewer));
            liveBots.forEach(bot -> { bot.player.tick(Collections.emptySet()); bot.player.sendRemovePlayerPacket(viewer); });
        }
        teams.clear(); registry.clear();
        tabBots.clear(); liveBots.clear(); active.clear();
        if(database!=null)database.close();
    }

    @EventHandler public void onJoin(PlayerJoinEvent event) {
        Bukkit.getScheduler().runTaskLater(this, () -> sendTab(event.getPlayer()), 10L);
    }

    @EventHandler(priority = EventPriority.HIGHEST)
    public void onPing(ServerListPingEvent event) {
        if (getConfig().getBoolean("settings.motd-count-enabled", true))
            event.setMaxPlayers(Math.max(event.getMaxPlayers(), Bukkit.getOnlinePlayers().size() + 1));
        // Bukkit не позволяет менять getNumPlayers; Bungee-модуль должен менять число на proxy.
    }

    private void sendTab(Player viewer) {
        if (!viewer.isOnline()) return;
        tabBots.forEach(bot -> bot.sendAddPlayerPacket(viewer));
    }

    private int fakeCount() { return active.size(); }

    private void ensureProfiles() {
        ConfigurationSection section=bots.getConfigurationSection("profiles");
        if(section==null){
            String[] first={"Shadow","Frost","Pixel","Craft","Night","Sky","Fire","Wolf","Storm","Dark","Light","Nova"};
            String[] second={"Fox","Miner","Alex","Steve","Hero","Dream","Blade","Rider","Bear","Spark"};
            int id=0;for(String a:first)for(String b:second){String key=String.format("bot%03d",++id),name=a+b+(10+random.nextInt(90));bots.set("profiles."+key+".name",name);bots.set("profiles."+key+".group","default");bots.set("profiles."+key+".ping",25+random.nextInt(100));}
            try{bots.save(new File(getDataFolder(),"bots.yml"));}catch(Exception ex){getLogger().warning("Cannot save profiles: "+ex.getMessage());}
            section=bots.getConfigurationSection("profiles");
        }
        if(section!=null)for(String key:section.getKeys(false)){ConfigurationSection c=section.getConfigurationSection(key);if(c!=null)profiles.add(new BotProfile(c.getString("name",key),c.getString("group","default"),c.getInt("ping",50)));}
        getLogger().info("Loaded "+profiles.size()+" reserve bot profiles.");
    }

    private void populationTick(){
        long now=System.currentTimeMillis();
        List<ActiveBot> expired=new ArrayList<>();for(ActiveBot bot:active.values())if(bot.expiresAt<=now)expired.add(bot);for(ActiveBot bot:expired)deactivate(bot);
        if(now<nextPopulationChange)return;int target=populationTarget();
        if(active.size()<target)activateOne();else if(active.size()>target&&!active.isEmpty())deactivate(new ArrayList<>(active.values()).get(random.nextInt(active.size())));
        int difference=Math.abs(target-active.size());long seconds=difference>=4?60+random.nextInt(120):120+random.nextInt(481);nextPopulationChange=now+seconds*1000;
    }
    private int populationTarget(){
        java.time.ZonedDateTime time=java.time.ZonedDateTime.now(java.time.ZoneId.of("Europe/Moscow")).plusMinutes(dailyMinuteJitter);int minute=time.getHour()*60+time.getMinute();
        int[] at={0,360,780,1200,1439};double[] value={4,6,9,13,5};int i=0;while(i<at.length-2&&minute>at[i+1])i++;double t=(minute-at[i])/(double)(at[i+1]-at[i]);double base=value[i]+(value[i+1]-value[i])*t;java.util.Random day=new java.util.Random(time.toLocalDate().toEpochDay());return Math.max(getConfig().getInt("population.minimum-bots",3),Math.min(getConfig().getInt("population.maximum-bots",15),(int)Math.round(base+(day.nextDouble()*2-1))));
    }
    private void activateOne(){
        long now=System.currentTimeMillis();List<BotProfile> available=new ArrayList<>();for(BotProfile p:profiles)if(!active.containsKey(p.name)&&database.cooldown(p.name)<=now)available.add(p);if(available.isEmpty())return;
        BotProfile profile=available.get(random.nextInt(available.size()));Location spawn=spawn(null);VirtualPlayer player=create(profile.name,profile.ping,profile.group,spawn.getWorld());player.setPos(vec(spawn));player.setYaw(spawn.getYaw());player.setPitch(spawn.getPitch());player.setOnGround(true);
        tabBots.add(player);realPlayers().forEach(player::sendAddPlayerPacket);MovingBot moving=null;if(random.nextDouble()<visibleChance){Point point=randomSafePoint(spawn.getWorld());moving=new MovingBot(player,spawn.getWorld(),point.vector(),3.4+random.nextDouble());liveBots.add(moving);}
        long expires=now+randomMinutes("population.session-minutes",60,360)*60000L;active.put(profile.name,new ActiveBot(profile,player,moving,expires));getLogger().info(profile.name+" joined ("+active.size()+" bots online)");
    }
    private void deactivate(ActiveBot bot){
        for(Player viewer:realPlayers()){bot.player.sendRemovePlayerPacket(viewer);}if(bot.moving!=null){bot.player.tick(Collections.emptySet());liveBots.remove(bot.moving);}tabBots.remove(bot.player);registry.remove(bot.player.getUuid());teams.remove(bot.profile.name);active.remove(bot.profile.name);database.quit(bot.profile.name,System.currentTimeMillis()+randomMinutes("population.profile-cooldown-minutes",120,360)*60000L);getLogger().info(bot.profile.name+" left ("+active.size()+" bots online)");
    }
    private Point randomSafePoint(World world){
        for(int attempt=0;attempt<80;attempt++){double centerX=getConfig().getDouble("population.region.center-x",30),centerZ=getConfig().getDouble("population.region.center-z",9),radius=getConfig().getDouble("population.region.radius",100);double x=centerX+(random.nextDouble()*2-1)*radius,z=centerZ+(random.nextDouble()*2-1)*radius;for(int y=Math.min(world.getMaxHeight()-2,world.getHighestBlockYAt((int)x,(int)z)+1);y>world.getMinHeight();y--){Block floor=world.getBlockAt((int)Math.floor(x),y-1,(int)Math.floor(z));if(!floor.isPassable()&&world.getBlockAt((int)x,y,(int)z).isPassable()&&world.getBlockAt((int)x,y+1,(int)z).isPassable())return new Point(world,x+.5,y,z+.5,0,0);}}
        Location fallback=world.getSpawnLocation();return new Point(world,fallback.getX(),fallback.getY(),fallback.getZ(),fallback.getYaw(),fallback.getPitch());
    }
    private long randomMinutes(String path,int fallbackMin,int fallbackMax){int min=getConfig().getInt(path+".min",fallbackMin),max=Math.max(min,getConfig().getInt(path+".max",fallbackMax));return min+random.nextInt(max-min+1);}
    private record BotProfile(String name,String group,int ping){}
    private static final class ActiveBot{final BotProfile profile;final VirtualPlayer player;final MovingBot moving;final long expiresAt;ActiveBot(BotProfile p,VirtualPlayer v,MovingBot m,long e){profile=p;player=v;moving=m;expiresAt=e;}}

    private VirtualPlayer create(String name, int ping, String group, World registrationWorld) {
        if (name.isBlank() || name.length() > 16) throw new IllegalArgumentException("name must be 1-16 characters");
        VirtualPlayer p = VirtualPlayer.create(); p.setName(name); p.setLatency(Math.max(0, ping)); p.setGameMode(GameMode.SURVIVAL);
        if (Bukkit.getPluginManager().isPluginEnabled("LuckPerms")) {
            try {
                LuckPerms lp = LuckPermsProvider.get();
                lp.getUserManager().modifyUser(p.getUuid(), user -> user.data().add(InheritanceNode.builder(group).build()));
            } catch (Exception ex) { getLogger().warning("LuckPerms hook failed for " + name + ": " + ex.getMessage()); }
        }
        BotTeamManager.Style style=teams.add(name, group, getConfig().getString("formatting.default-suffix", " &dБЕТА"));
        String label=style.prefix()+ChatColor.GRAY+name+style.suffix();
        p.setDisplayName(LegacyComponentSerializer.legacySection().deserialize(label));
        registry.register(name, p.getUuid(), registrationWorld);
        return p;
    }

    private List<Player> realPlayers() {
        List<Player> result = new ArrayList<>();
        for (Player player : Bukkit.getOnlinePlayers()) if (!registry.isFake(player.getUniqueId())) result.add(player);
        return result;
    }

    private void tick(int ticks) {
        datasets.tick(); populationTick();
        for (MovingBot b : liveBots) {
            b.move(ticks / 20D);
            Set<Player> viewers = new HashSet<>();
            for (Player player : b.world.getPlayers()) if (!registry.isFake(player.getUniqueId())) viewers.add(player);
            b.player.tick(viewers);
        }
    }

    @Override public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (!(sender instanceof Player player)) { sender.sendMessage("Player only"); return true; }
        if (!player.hasPermission("elytrixbots.dataset")) { player.sendMessage(ChatColor.RED + "Нет прав."); return true; }
        if (args.length >= 3 && args[0].equalsIgnoreCase("dataset") && args[1].equalsIgnoreCase("start")) {
            String name=args.length>=4?args[3]:String.valueOf(System.currentTimeMillis()/1000);
            if (datasets.start(player, args[2].equalsIgnoreCase("all")?"всё":args[2].toLowerCase(Locale.ROOT),name)) player.sendMessage(ChatColor.GREEN + "Запись «"+args[2]+"» началась.");
            else player.sendMessage(ChatColor.RED + "Выбери тип через TAB или останови текущую запись.");
            return true;
        }
        if (args.length >= 2 && args[0].equalsIgnoreCase("dataset") && args[1].equalsIgnoreCase("stop")) {
            String result=datasets.stop(player);
            player.sendMessage(result == null ? ChatColor.RED + "Запись не запущена." : ChatColor.GREEN + "Сохранено: " + result);
            return true;
        }
        player.sendMessage(ChatColor.YELLOW + "/elytrixbots dataset start <тип> [имя] | stop"); return true;
    }

    @Override public List<String> onTabComplete(CommandSender sender,Command command,String alias,String[] args){
        if(args.length==1)return filter(List.of("dataset"),args[0]);
        if(args.length==2&&args[0].equalsIgnoreCase("dataset"))return filter(List.of("start","stop"),args[1]);
        if(args.length==3&&args[0].equalsIgnoreCase("dataset")&&args[1].equalsIgnoreCase("start"))return filter(DatasetManager.TYPES,args[2]);
        if(args.length==4&&args[1].equalsIgnoreCase("start"))return List.of("пример_1");
        return Collections.emptyList();
    }
    private List<String> filter(List<String> values,String input){String q=input.toLowerCase(Locale.ROOT);List<String> result=new ArrayList<>();for(String value:values)if(value.startsWith(q))result.add(value);return result;}


    private Location spawn(ConfigurationSection explicit) {
        if (explicit != null) { Point p = point(explicit, null); return new Location(p.world, p.x, p.y, p.z, p.yaw, p.pitch); }
        if (getConfig().getBoolean("settings.use-essentials-spawn", true)) {
            File f = new File("plugins/Essentials/spawn.yml");
            if (f.isFile()) {
                ConfigurationSection s = YamlConfiguration.loadConfiguration(f).getConfigurationSection("spawns.default");
                if (s != null) {
                    World w = Bukkit.getWorld(s.getString("world-name", "world"));
                    if (w != null) return new Location(w, s.getDouble("x"), s.getDouble("y"), s.getDouble("z"), (float)s.getDouble("yaw"), (float)s.getDouble("pitch"));
                }
            }
        }
        return Bukkit.getWorlds().get(0).getSpawnLocation();
    }

    private Point point(ConfigurationSection c, World fallback) {
        if (c == null) throw new IllegalArgumentException("missing target");
        World w = c.contains("world") ? Bukkit.getWorld(c.getString("world", "world")) : fallback;
        if (w == null) throw new IllegalArgumentException("world not found");
        return new Point(w, c.getDouble("x"), c.getDouble("y"), c.getDouble("z"), (float)c.getDouble("yaw"), (float)c.getDouble("pitch"));
    }
    private static Vec3d vec(Location l) { return new Vec3d(l.getX(), l.getY(), l.getZ()); }
    private record Point(World world,double x,double y,double z,float yaw,float pitch) { Vec3d vector(){return new Vec3d(x,y,z);} }

    private final class MovingBot {
        final VirtualPlayer player; final World world; Vec3d target; final double speed; List<Vec3d> route;
        final double moveFactor=.96+random.nextDouble()*.08,turnFactor=.90+random.nextDouble()*.20;
        final float learnedTurn=datasets.learnedTurnSpeed()*(float)turnFactor;
        List<DatasetManager.MotionSample> sequence=Collections.emptyList();int frame,idleCooldown,routeIndex,jumpCooldown,stuckTicks,ambientCooldown=100+random.nextInt(301),ambientTicks,spawnDelay=40+random.nextInt(121);boolean arrived,airborneLastTick,ambientJump;double verticalVelocity,airborneStartY,velocityX,velocityZ;float lookYaw,lookPitch,ambientYaw,ambientPitch;double currentPace=1,targetPace=1;int paceTicks;long afkUntil;Vec3d lastProgressPos;
        MovingBot(VirtualPlayer p,World w,Vec3d t,double s){player=p;world=w;target=t;speed=Math.max(.1,s);route=GridPathfinder.find(w,p.getPos(),t);lookYaw=p.getYaw();lookPitch=p.getPitch();lastProgressPos=p.getPos();}
        void setTarget(Vec3d next){target=next;route=GridPathfinder.find(world,player.getPos(),target);routeIndex=0;arrived=false;spawnDelay=20+random.nextInt(61);stuckTicks=0;lastProgressPos=player.getPos();}
        DatasetManager.MotionSample next(){if(sequence.isEmpty()){sequence=datasets.randomSequence(random);if(sequence.isEmpty())return null;frame=random.nextInt(sequence.size());}return sequence.get(frame++%sequence.size());}
        void move(double seconds){
            Vec3d p=player.getPos();
            if(jumpCooldown>0)jumpCooldown--;
            if(spawnDelay-->0){applyPhysics(p,p.x,p.z,seconds);if(spawnDelay==10)lookYaw+=35-random.nextInt(71);smoothLook();return;}
            if(arrived){applyPhysics(p,p.x,p.z,seconds);idleBehavior();if(System.currentTimeMillis()>=afkUntil){Point point=randomSafePoint(world);setTarget(point.vector());}return;}
            DatasetManager.MotionSample sample=next();if(sample==null)sample=DatasetManager.MotionSample.neutral();
            Vec3d waypoint=routeIndex<route.size()?route.get(routeIndex):target;
            double dx=waypoint.x-p.x,dz=waypoint.z-p.z,distance=Math.hypot(dx,dz);
            if(distance<.22){
                if(routeIndex<route.size()){
                    routeIndex++;
                    if(routeIndex>=route.size()&&Math.hypot(target.x-p.x,target.z-p.z)>.6){route=GridPathfinder.find(world,p,target);routeIndex=0;}
                    return;
                }
                if(Math.hypot(target.x-p.x,target.z-p.z)>.6){route=GridPathfinder.find(world,p,target);routeIndex=0;return;}
                arrived=true;afkUntil=System.currentTimeMillis()+randomMinutes("population.afk-minutes",5,60)*60000L;player.setSprinting(false);idleBehavior();return;
            }
            if(ambientTicks>0)ambientTicks--;else{ambientYaw=approach(ambientYaw,0,.35F);ambientPitch=approach(ambientPitch,0,.25F);if(--ambientCooldown<=0){ambientTicks=20+random.nextInt(41);ambientYaw=(random.nextBoolean()?1:-1)*(5+random.nextFloat()*13);ambientPitch=-5+random.nextFloat()*10;ambientJump=random.nextInt(4)==0;ambientCooldown=120+random.nextInt(481);}}
            float desired=(float)Math.toDegrees(Math.atan2(-dx,dz))+ambientYaw;
            float turnLimit=Math.max(1.2F,Math.min(learnedTurn,learnedTurn*(.65F+Math.min(.35F,Math.abs(sample.yawDelta)/20F))));
            player.setYaw(approachAngle(player.getYaw(),desired,turnLimit));
            player.setPitch(approach(player.getPitch(),Math.max(-90,Math.min(90,ambientPitch+sample.pitchDelta*(float)turnFactor*.03F)),.8F));
            // Сначала полностью разворачиваемся, только потом начинаем идти — движения задом не будет.
            // Небольшие и средние повороты выполняются на ходу; стоим только если цель почти за спиной.
            if(Math.abs(angleDifference(player.getYaw(),desired))>85F){player.setSprinting(false);applyPhysics(p,p.x,p.z,seconds);return;}
            if(paceTicks--<=0){targetPace=.82+random.nextDouble()*.34;paceTicks=40+random.nextInt(121);}
            currentPace+=Math.max(-.008,Math.min(.008,targetPace-currentPace));
            double amount=Math.min(distance,speed*seconds*moveFactor*currentPace);
            double dirX=dx/distance,dirZ=dz/distance;
            // Реальное A/D из dataset добавляется как небольшая боковая составляющая, а не зигзаг маршрута.
            double strafe=Math.max(-.16,Math.min(.16,sample.strafe/Math.max(.01,sample.horizontal)));
            double wishX=dirX+dirZ*strafe,wishZ=dirZ-dirX*strafe,norm=Math.hypot(wishX,wishZ);wishX=wishX/norm*amount;wishZ=wishZ/norm*amount;
            // Плавное ускорение и торможение как у управляемого игрока.
            double acceleration=Math.max(.008,amount*.14);
            velocityX=approachDouble(velocityX,wishX,acceleration);velocityZ=approachDouble(velocityZ,wishZ,acceleration);
            double nx=p.x+velocityX,nz=p.z+velocityZ;
            double currentGround=groundY(p.x,p.y,p.z),aheadGround=groundY(nx,p.y,nz);
            if(Double.isNaN(currentGround)){emergencyGround(p,seconds);return;}
            boolean grounded=p.y<=currentGround+.04&&verticalVelocity<=0;
            // Смотрим дальше собственного шага и начинаем прыжок до столкновения с гранью блока.
            double probeX=p.x+dx/distance*.68,probeZ=p.z+dz/distance*.68,probeGround=groundY(probeX,p.y,probeZ);
            if(!Double.isNaN(probeGround)&&probeGround-currentGround>.75&&grounded&&jumpCooldown==0){verticalVelocity=Math.min(.48,Math.max(.44,datasets.learnedJumpVelocity(seconds)/20D));jumpCooldown=12;}
            else if(ambientJump&&grounded&&!Double.isNaN(probeGround)&&Math.abs(probeGround-currentGround)<.08&&jumpCooldown==0){verticalVelocity=.42;jumpCooldown=12;ambientJump=false;}
            // Плиты проходим прямо, но никогда не отключаем точную проверку коллизии при спуске.
            if(Double.isNaN(aheadGround)||hazardAt(nx,aheadGround,nz)||!clearAt(nx,Math.max(p.y,aheadGround),nz)){nx=p.x;nz=p.z;velocityX=velocityZ=0;aheadGround=currentGround;}
            if(aheadGround-currentGround>.75&&p.y<aheadGround-.88){nx=p.x;nz=p.z;velocityX=velocityZ=0;}
            player.setShiftKeyDown(sample.sneak&&!player.isSprinting());player.setSprinting(!sample.sneak);
            applyPhysics(p,nx,nz,seconds);
            if(Math.hypot(p.x-lastProgressPos.x,p.z-lastProgressPos.z)>.20){lastProgressPos=p;stuckTicks=0;}
            else if(++stuckTicks>45){
                // Выход из углубления: перестраиваем путь и выполняем один обычный прыжок, если зажаты блоками.
                route=GridPathfinder.find(world,player.getPos(),target);routeIndex=0;stuckTicks=0;lastProgressPos=player.getPos();
                Vec3d now=player.getPos();double floor=groundY(now.x,now.y,now.z);
                if(!Double.isNaN(floor)&&now.y<=floor+.04&&jumpCooldown==0&&realObstacleAhead(now)){verticalVelocity=.42;jumpCooldown=12;}
            }
        }
        void applyPhysics(Vec3d p,double nx,double nz,double seconds){
            double ground=supportY(nx,p.y,nz);if(Double.isNaN(ground)){emergencyGround(p,seconds);return;}
            double ny=p.y;boolean grounded=p.y<=ground+.025&&verticalVelocity<=0;
            if(grounded&&ground>=p.y-.025&&ground-p.y<=.60){ny=ground;verticalVelocity=0;}
            else {
                int elapsed=Math.max(1,(int)Math.round(seconds*20));
                for(int i=0;i<elapsed;i++){ny+=verticalVelocity;verticalVelocity=(verticalVelocity-.08)*.98;}
                if(ny<=ground){ny=ground;verticalVelocity=0;}
            }
            boolean onGround=Math.abs(ny-ground)<.025;
            player.setOnGround(onGround);player.setPos(new Vec3d(nx,ny,nz));
            if(!airborneLastTick&&!onGround)airborneStartY=p.y;
            if(airborneLastTick&&onGround&&!arrived&&airborneStartY-ny>.75){route=GridPathfinder.find(world,new Vec3d(nx,ny,nz),target);routeIndex=0;stuckTicks=0;lastProgressPos=new Vec3d(nx,ny,nz);}
            airborneLastTick=!onGround;
        }
        void idleBehavior(){smoothLook();if(idleCooldown-->0)return;DatasetManager.MotionSample sample=datasets.idleSample(random);player.setShiftKeyDown(sample.sneak);player.setSprinting(false);lookYaw=player.getYaw()+sample.yawDelta*(float)turnFactor;lookPitch=Math.max(-90,Math.min(90,player.getPitch()+sample.pitchDelta*(float)turnFactor));idleCooldown=100+random.nextInt(1501);}
        void smoothLook(){player.setYaw(approachAngle(player.getYaw(),lookYaw,Math.max(1.5F,learnedTurn*.5F)));player.setPitch(approach(player.getPitch(),lookPitch,2F));}
        double approachDouble(double from,double to,double max){return from+Math.max(-max,Math.min(max,to-from));}
        float approach(float from,float to,float max){return from+Math.max(-max,Math.min(max,to-from));}
        float approachAngle(float from,float to,float max){float d=angleDifference(from,to);return from+Math.max(-max,Math.min(max,d));}
        float angleDifference(float from,float to){float d=to-from;while(d>180)d-=360;while(d<-180)d+=360;return d;}
        boolean realObstacleAhead(Vec3d p){
            Vec3d waypoint=routeIndex<route.size()?route.get(routeIndex):target;double dx=waypoint.x-p.x,dz=waypoint.z-p.z,d=Math.hypot(dx,dz);if(d<.01)return false;
            double current=groundY(p.x,p.y,p.z),ahead=groundY(p.x+dx/d*.68,p.y,p.z+dz/d*.68);return !Double.isNaN(current)&&!Double.isNaN(ahead)&&ahead-current>.75;
        }
        boolean clearAt(double x,double y,double z){
            BoundingBox body=new BoundingBox(x-.29,y+.001,z-.29,x+.29,y+1.79,z+.29);
            for(int bx=(int)Math.floor(x-.29);bx<=(int)Math.floor(x+.29);bx++)for(int bz=(int)Math.floor(z-.29);bz<=(int)Math.floor(z+.29);bz++)for(int by=(int)Math.floor(y);by<=(int)Math.floor(y+1.79);by++){
                Block block=world.getBlockAt(bx,by,bz);if(!block.isPassable()&&block.getBoundingBox().overlaps(body))return false;
            }return true;
        }
        boolean hazardAt(double x,double y,double z){return hazard(world.getBlockAt((int)Math.floor(x),(int)Math.floor(y-.01),(int)Math.floor(z)));}
        boolean hazard(Block block){String type=block.getType().name();if(getConfig().getBoolean("settings.physics.avoid-liquids",true)&&(type.contains("WATER")||type.contains("LAVA")))return true;return getConfig().getBoolean("settings.physics.avoid-hazards",true)&&(type.contains("FIRE")||type.contains("CACTUS")||type.contains("MAGMA")||type.contains("CAMPFIRE"));}
        void emergencyGround(Vec3d p,double seconds){player.setSprinting(false);if(!getConfig().getBoolean("settings.physics.anti-flight",true))return;if(p.y<=world.getMinHeight()+1){player.setPos(vec(world.getSpawnLocation()));verticalVelocity=0;return;}double ny=p.y;int elapsed=Math.max(1,(int)Math.round(seconds*20));for(int i=0;i<elapsed;i++){ny+=verticalVelocity;verticalVelocity=(verticalVelocity-.08)*.98;}player.setPos(new Vec3d(p.x,ny,p.z));player.setOnGround(false);}
        double supportY(double x,double y,double z){
            double best=Double.NaN;double[] offsets={0,-.28,.28};
            for(double ox:offsets)for(double oz:offsets){double value=groundY(x+ox,y,z+oz);if(!Double.isNaN(value)&&value<=y+.60&&(Double.isNaN(best)||value>best))best=value;}
            return best;
        }
        double groundY(double x,double y,double z){
            if(!getConfig().getBoolean("settings.physics.enabled",true))return y;int bx=(int)Math.floor(x),bz=(int)Math.floor(z),base=(int)Math.floor(y),up=getConfig().getInt("settings.physics.max-step-height",1),down=getConfig().getInt("settings.physics.max-fall-check",64);
            for(int by=base+up-1;by>=Math.max(world.getMinHeight(),base-down-1);by--){Block floor=world.getBlockAt(bx,by,bz);if(floor.isPassable())continue;double top=floor.getBoundingBox().getMaxY();if(top<=1.5)top+=by;int feet=(int)Math.ceil(top);if(world.getBlockAt(bx,feet,bz).isPassable()&&world.getBlockAt(bx,feet+1,bz).isPassable())return top;}return Double.NaN;
        }
    }
}