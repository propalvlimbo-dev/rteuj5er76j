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

public final class ElytrixBotsPlugin extends JavaPlugin implements Listener, CommandExecutor {
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
        Objects.requireNonNull(getCommand("elytrixbots")).setExecutor(this);
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
            if (datasets.start(player, args[2])) player.sendMessage(ChatColor.GREEN + "Запись dataset началась.");
            else player.sendMessage(ChatColor.RED + "Неверное имя или запись уже идёт.");
            return true;
        }
        if (args.length >= 2 && args[0].equalsIgnoreCase("dataset") && args[1].equalsIgnoreCase("stop")) {
            String result=datasets.stop(player);
            player.sendMessage(result == null ? ChatColor.RED + "Запись не запущена." : ChatColor.GREEN + "Сохранено: " + result);
            return true;
        }
        player.sendMessage(ChatColor.YELLOW + "/elytrixbots dataset start <имя> | stop"); return true;
    }

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
        final VirtualPlayer player; final World world; final Vec3d target; final double speed;
        final double moveFactor=.96+random.nextDouble()*.08, turnFactor=.90+random.nextDouble()*.20, fallFactor=.98+random.nextDouble()*.04;
        List<DatasetManager.MotionSample> sequence=Collections.emptyList(); int frame, idleCooldown; boolean arrived; double verticalVelocity;
        MovingBot(VirtualPlayer p,World w,Vec3d t,double s){player=p;world=w;target=t;speed=Math.max(.1,s);}
        DatasetManager.MotionSample next(){
            if(sequence.isEmpty()){sequence=datasets.randomSequence(random);if(sequence.isEmpty())return null;frame=random.nextInt(sequence.size());}
            DatasetManager.MotionSample sample=sequence.get(frame++%sequence.size());
            return sample;
        }
        void move(double seconds){
            if(!datasets.hasSamples()){player.setSprinting(false);player.setShiftKeyDown(false);return;}
            if(arrived){idleBehavior();return;}
            DatasetManager.MotionSample sample=next(); if(sample==null)return;
            Vec3d p=player.getPos();double dx=target.x-p.x,dz=target.z-p.z,distance=Math.sqrt(dx*dx+dz*dz);
            if(distance<.03){arrived=true;player.setSprinting(false);idleBehavior();return;}
            player.setShiftKeyDown(sample.sneak);player.setSprinting(sample.sprint);
            double amount=Math.min(distance,Math.min(sample.horizontal*moveFactor,speed*seconds*1.25));
            double currentGround=groundY(p.x,p.y,p.z);if(Double.isNaN(currentGround)){emergencyGround(p);return;}
            NavCandidate candidate=chooseSafeCandidate(p,dx/distance,dz/distance,amount,currentGround,sample);
            if(candidate==null){player.setSprinting(false);player.setShiftKeyDown(false);idleBehavior();return;}
            double nx=candidate.x,nz=candidate.z,ground=candidate.ground;
            boolean standing=Math.abs(p.y-currentGround)<.04;
            boolean fullObstacle=ground-currentGround>.60;
            if(ground>p.y+.60){ // не заходим внутрь стены: сначала набираем высоту прыжком
                nx=p.x;nz=p.z;ground=currentGround;
            }
            if(standing&&ground>=p.y-.04){
                verticalVelocity=0;
                // Прыжок из dataset применяется только когда впереди настоящий полный блок.
                if(fullObstacle&&sample.vertical>.015) verticalVelocity=Math.min(8.0,Math.max(3.5,sample.vertical/seconds*fallFactor));
            } else verticalVelocity=Math.max(-18,verticalVelocity-24.0*seconds);
            double ny=p.y+verticalVelocity*seconds;
            if(verticalVelocity<=0&&ny<=ground){ny=ground;verticalVelocity=0;}
            // Плиты и небольшие ступени проходятся по их реальной высоте.
            if(standing&&ground>p.y&&ground-p.y<=.60&&verticalVelocity==0)ny=Math.min(ground,p.y+.20);
            float targetYaw=(float)Math.toDegrees(Math.atan2(-dx,dz));
            player.setYaw(targetYaw+sample.yawDelta*(float)turnFactor);
            player.setPitch(Math.max(-90F,Math.min(90F,player.getPitch()+sample.pitchDelta*(float)turnFactor)));
            player.setOnGround(Math.abs(ny-ground)<.02);player.setPos(new Vec3d(nx,ny,nz));
        }
        NavCandidate chooseSafeCandidate(Vec3d p,double dirX,double dirZ,double amount,double currentGround,DatasetManager.MotionSample sample){
            // Стабильное направление: обход будет добавлен планировщиком маршрута, а не рывками влево/вправо.
            double[] angles={0};
            for(double angle:angles){
                double r=Math.toRadians(angle),rx=dirX*Math.cos(r)-dirZ*Math.sin(r),rz=dirX*Math.sin(r)+dirZ*Math.cos(r);
                double x=p.x+rx*amount,z=p.z+rz*amount,ground=groundY(x,p.y,z);if(Double.isNaN(ground))continue;
                double delta=ground-currentGround,maxDrop=getConfig().getDouble("settings.physics.max-safe-drop",3.5);
                if(delta < -maxDrop)continue;
                int bx=(int)Math.floor(x),bz=(int)Math.floor(z),feet=(int)Math.ceil(Math.max(p.y,ground));
                Block body=world.getBlockAt(bx,feet,bz),head=world.getBlockAt(bx,feet+1,bz),floor=world.getBlockAt(bx,(int)Math.floor(ground-.01),bz);
                if(!body.isPassable()||!head.isPassable()||hazard(body)||hazard(floor))continue;
                return new NavCandidate(x,z,ground);
            }return null;
        }
        boolean hazard(Block block){
            String type=block.getType().name();
            if(getConfig().getBoolean("settings.physics.avoid-liquids",true)&&(type.contains("WATER")||type.contains("LAVA")))return true;
            return getConfig().getBoolean("settings.physics.avoid-hazards",true)&&(type.contains("FIRE")||type.contains("CACTUS")||type.contains("MAGMA")||type.contains("CAMPFIRE"));
        }
        void emergencyGround(Vec3d p){
            player.setSprinting(false);player.setShiftKeyDown(false);
            if(!getConfig().getBoolean("settings.physics.anti-flight",true))return;
            if(p.y<=world.getMinHeight()+1){Location spawn=world.getSpawnLocation();player.setPos(vec(spawn));verticalVelocity=0;return;}
            verticalVelocity=Math.max(-12,verticalVelocity-.981);player.setPos(new Vec3d(p.x,p.y+verticalVelocity*.1,p.z));player.setOnGround(false);
        }
        record NavCandidate(double x,double z,double ground){}
        void idleBehavior(){
            if(idleCooldown-->0)return;DatasetManager.MotionSample sample=next();if(sample==null)return;
            player.setShiftKeyDown(sample.sneak);player.setSprinting(false);
            player.setYaw(player.getYaw()+sample.yawDelta*(float)turnFactor);
            player.setPitch(Math.max(-90F,Math.min(90F,player.getPitch()+sample.pitchDelta*(float)turnFactor)));
            idleCooldown=3+random.nextInt(18);
        }
        double groundY(double x,double y,double z){
            if(!getConfig().getBoolean("settings.physics.enabled",true))return y;
            int bx=(int)Math.floor(x),bz=(int)Math.floor(z),base=(int)Math.floor(y),up=getConfig().getInt("settings.physics.max-step-height",1),down=getConfig().getInt("settings.physics.max-fall-check",4);
            for(int blockY=base+up-1;blockY>=base-down-1;blockY--){
                Block floor=world.getBlockAt(bx,blockY,bz);if(floor.isPassable())continue;
                double top=blockY+1D;
                try{double shapeTop=floor.getBoundingBox().getMaxY();top=shapeTop<=1.5?blockY+shapeTop:shapeTop;}catch(Throwable ignored){}
                Block body=world.getBlockAt(bx,(int)Math.floor(top+.01),bz),head=world.getBlockAt(bx,(int)Math.floor(top+1.01),bz);
                if(body.isPassable()&&head.isPassable())return top;
            }return Double.NaN;
        }
    }
}