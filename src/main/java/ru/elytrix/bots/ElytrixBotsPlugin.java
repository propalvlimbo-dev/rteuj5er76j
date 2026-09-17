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

    @Override public void onEnable() {
        saveDefaultConfig(); saveResource("bots.yml", false);
        bots = YamlConfiguration.loadConfiguration(new File(getDataFolder(), "bots.yml"));
        datasets = new DatasetManager(this);
        loadBots(); Bukkit.getPluginManager().registerEvents(this, this);
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
        tabBots.clear(); liveBots.clear();
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
        liveBots.forEach(bot -> bot.player.sendAddPlayerPacket(viewer));
    }

    private int fakeCount() { return tabBots.size() + liveBots.size(); }

    private void loadBots() {
        ConfigurationSection tabs = bots.getConfigurationSection("tab-bots");
        if (tabs != null) for (String key : tabs.getKeys(false)) {
            ConfigurationSection c = tabs.getConfigurationSection(key); if (c == null) continue;
            VirtualPlayer bot = create(c.getString("name", key), c.getInt("ping", 50), c.getString("luckperms-group", "default"), Bukkit.getWorlds().get(0));
            tabBots.add(bot); realPlayers().forEach(bot::sendAddPlayerPacket);
        }
        ConfigurationSection lives = bots.getConfigurationSection("live-bots");
        if (lives != null) for (String key : lives.getKeys(false)) {
            ConfigurationSection c = lives.getConfigurationSection(key); if (c == null) continue;
            try {
                Location spawn = spawn(c.getConfigurationSection("spawn"));
                Point target = point(c.getConfigurationSection("target"), spawn.getWorld());
                VirtualPlayer player = create(c.getString("name", key), c.getInt("ping", 50), c.getString("luckperms-group", "default"), spawn.getWorld());
                player.setPos(vec(spawn)); player.setYaw(spawn.getYaw()); player.setPitch(spawn.getPitch()); player.setSprinting(false); player.setOnGround(true);
                liveBots.add(new MovingBot(player, spawn.getWorld(), target.vector(), c.getDouble("speed-blocks-per-second", 3.8)));
                realPlayers().forEach(player::sendAddPlayerPacket);
            } catch (RuntimeException ex) { getLogger().warning("Skipped bot " + key + ": " + ex.getMessage()); }
        }
    }

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
        datasets.tick();
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
            if (datasets.start(player, args[2].toLowerCase(Locale.ROOT),name)) player.sendMessage(ChatColor.GREEN + "Запись «"+args[2]+"» началась.");
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
        final VirtualPlayer player; final World world; final Vec3d target; final double speed; List<Vec3d> route;
        final double moveFactor=.96+random.nextDouble()*.08,turnFactor=.90+random.nextDouble()*.20;
        final float learnedTurn=datasets.learnedTurnSpeed()*(float)turnFactor;
        List<DatasetManager.MotionSample> sequence=Collections.emptyList();int frame,idleCooldown,routeIndex,jumpCooldown,stuckTicks,spawnDelay=40+random.nextInt(121);boolean arrived;double verticalVelocity;float lookYaw,lookPitch;Vec3d lastProgressPos;
        MovingBot(VirtualPlayer p,World w,Vec3d t,double s){player=p;world=w;target=t;speed=Math.max(.1,s);route=GridPathfinder.find(w,p.getPos(),t);lookYaw=p.getYaw();lookPitch=p.getPitch();lastProgressPos=p.getPos();}
        DatasetManager.MotionSample next(){if(sequence.isEmpty()){sequence=datasets.randomSequence(random);if(sequence.isEmpty())return null;frame=random.nextInt(sequence.size());}return sequence.get(frame++%sequence.size());}
        void move(double seconds){
            Vec3d p=player.getPos();
            if(jumpCooldown>0)jumpCooldown--;
            if(spawnDelay-->0){applyPhysics(p,p.x,p.z,seconds);if(spawnDelay==10)lookYaw+=35-random.nextInt(71);smoothLook();return;}
            if(arrived){applyPhysics(p,p.x,p.z,seconds);idleBehavior();return;}
            DatasetManager.MotionSample sample=next();if(sample==null)sample=DatasetManager.MotionSample.neutral();
            Vec3d waypoint=routeIndex<route.size()?route.get(routeIndex):target;
            double dx=waypoint.x-p.x,dz=waypoint.z-p.z,distance=Math.hypot(dx,dz);
            if(distance<.22){if(routeIndex<route.size()){routeIndex++;return;}arrived=true;player.setSprinting(false);idleBehavior();return;}
            float desired=(float)Math.toDegrees(Math.atan2(-dx,dz));
            player.setYaw(approachAngle(player.getYaw(),desired,learnedTurn));
            player.setPitch(approach(player.getPitch(),Math.max(-90,Math.min(90,player.getPitch()+sample.pitchDelta*(float)turnFactor*.03F)),.8F));
            // Сначала полностью разворачиваемся, только потом начинаем идти — движения задом не будет.
            if(Math.abs(angleDifference(player.getYaw(),desired))>7F){player.setSprinting(false);applyPhysics(p,p.x,p.z,seconds);return;}
            double amount=Math.min(distance,speed*seconds*moveFactor),nx=p.x+dx/distance*amount,nz=p.z+dz/distance*amount;
            double currentGround=groundY(p.x,p.y,p.z),aheadGround=groundY(nx,p.y,nz);
            if(Double.isNaN(currentGround)){emergencyGround(p,seconds);return;}
            boolean grounded=p.y<=currentGround+.04&&verticalVelocity<=0;
            // Смотрим дальше собственного шага и начинаем прыжок до столкновения с гранью блока.
            double probeX=p.x+dx/distance*.68,probeZ=p.z+dz/distance*.68,probeGround=groundY(probeX,p.y,probeZ);
            if(!Double.isNaN(probeGround)&&probeGround-currentGround>.60&&grounded&&jumpCooldown==0){verticalVelocity=Math.min(.48,Math.max(.44,datasets.learnedJumpVelocity(seconds)/20D));jumpCooldown=12;}
            if(Double.isNaN(aheadGround)||hazardAt(nx,aheadGround,nz)||!clearAt(nx,Math.max(p.y,aheadGround),nz)){nx=p.x;nz=p.z;aheadGround=currentGround;}
            if(aheadGround-currentGround>.60&&p.y<aheadGround-.88){nx=p.x;nz=p.z;}
            player.setShiftKeyDown(sample.sneak&&!player.isSprinting());player.setSprinting(!sample.sneak);
            applyPhysics(p,nx,nz,seconds);
            if(Math.hypot(p.x-lastProgressPos.x,p.z-lastProgressPos.z)>.20){lastProgressPos=p;stuckTicks=0;}
            else if(++stuckTicks>60){route=GridPathfinder.find(world,player.getPos(),target);routeIndex=0;stuckTicks=0;lastProgressPos=player.getPos();}
        }
        void applyPhysics(Vec3d p,double nx,double nz,double seconds){
            double ground=groundY(nx,p.y,nz);if(Double.isNaN(ground)){emergencyGround(p,seconds);return;}
            double ny=p.y;boolean grounded=p.y<=ground+.025&&verticalVelocity<=0;
            if(grounded&&ground>=p.y-.025&&ground-p.y<=.60){ny=ground;verticalVelocity=0;}
            else {
                int elapsed=Math.max(1,(int)Math.round(seconds*20));
                for(int i=0;i<elapsed;i++){ny+=verticalVelocity;verticalVelocity=(verticalVelocity-.08)*.98;}
                if(ny<=ground){ny=ground;verticalVelocity=0;}
            }
            player.setOnGround(Math.abs(ny-ground)<.025);player.setPos(new Vec3d(nx,ny,nz));
        }
        void idleBehavior(){smoothLook();if(idleCooldown-->0)return;DatasetManager.MotionSample sample=datasets.idleSample(random);player.setShiftKeyDown(sample.sneak);player.setSprinting(false);lookYaw=player.getYaw()+sample.yawDelta*(float)turnFactor;lookPitch=Math.max(-90,Math.min(90,player.getPitch()+sample.pitchDelta*(float)turnFactor));idleCooldown=100+random.nextInt(1501);}
        void smoothLook(){player.setYaw(approachAngle(player.getYaw(),lookYaw,2.5F));player.setPitch(approach(player.getPitch(),lookPitch,2F));}
        float approach(float from,float to,float max){return from+Math.max(-max,Math.min(max,to-from));}
        float approachAngle(float from,float to,float max){float d=angleDifference(from,to);return from+Math.max(-max,Math.min(max,d));}
        float angleDifference(float from,float to){float d=to-from;while(d>180)d-=360;while(d<-180)d+=360;return d;}
        boolean clearAt(double x,double y,double z){
            int feet=(int)Math.ceil(y);double[] offsets={-.29,.29};
            for(double ox:offsets)for(double oz:offsets){int bx=(int)Math.floor(x+ox),bz=(int)Math.floor(z+oz);if(!world.getBlockAt(bx,feet,bz).isPassable()||!world.getBlockAt(bx,feet+1,bz).isPassable())return false;}
            return true;
        }
        boolean hazardAt(double x,double y,double z){return hazard(world.getBlockAt((int)Math.floor(x),(int)Math.floor(y-.01),(int)Math.floor(z)));}
        boolean hazard(Block block){String type=block.getType().name();if(getConfig().getBoolean("settings.physics.avoid-liquids",true)&&(type.contains("WATER")||type.contains("LAVA")))return true;return getConfig().getBoolean("settings.physics.avoid-hazards",true)&&(type.contains("FIRE")||type.contains("CACTUS")||type.contains("MAGMA")||type.contains("CAMPFIRE"));}
        void emergencyGround(Vec3d p,double seconds){player.setSprinting(false);if(!getConfig().getBoolean("settings.physics.anti-flight",true))return;if(p.y<=world.getMinHeight()+1){player.setPos(vec(world.getSpawnLocation()));verticalVelocity=0;return;}double ny=p.y;int elapsed=Math.max(1,(int)Math.round(seconds*20));for(int i=0;i<elapsed;i++){ny+=verticalVelocity;verticalVelocity=(verticalVelocity-.08)*.98;}player.setPos(new Vec3d(p.x,ny,p.z));player.setOnGround(false);}
        double groundY(double x,double y,double z){
            if(!getConfig().getBoolean("settings.physics.enabled",true))return y;int bx=(int)Math.floor(x),bz=(int)Math.floor(z),base=(int)Math.floor(y),up=getConfig().getInt("settings.physics.max-step-height",1),down=getConfig().getInt("settings.physics.max-fall-check",64);
            for(int by=base+up-1;by>=Math.max(world.getMinHeight(),base-down-1);by--){Block floor=world.getBlockAt(bx,by,bz);if(floor.isPassable())continue;double top=floor.getBoundingBox().getMaxY();if(top<=1.5)top+=by;int feet=(int)Math.ceil(top);if(world.getBlockAt(bx,feet,bz).isPassable()&&world.getBlockAt(bx,feet+1,bz).isPassable())return top;}return Double.NaN;
        }
    }
}