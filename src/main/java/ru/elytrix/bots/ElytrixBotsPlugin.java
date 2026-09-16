package ru.elytrix.bots;

import dev.by1337.virtualentity.api.virtual.player.VirtualPlayer;
import net.luckperms.api.LuckPerms;
import net.luckperms.api.LuckPermsProvider;
import net.luckperms.api.node.types.InheritanceNode;
import org.bukkit.*;
import org.bukkit.block.Block;
import org.bukkit.configuration.ConfigurationSection;
import org.bukkit.configuration.file.YamlConfiguration;
import org.bukkit.entity.Player;
import org.bukkit.event.*;
import org.bukkit.event.player.*;
import org.bukkit.event.server.ServerListPingEvent;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.scheduler.BukkitTask;
import org.by1337.blib.geom.Vec3d;

import java.io.File;
import java.util.*;

public final class ElytrixBotsPlugin extends JavaPlugin implements Listener {
    private final List<VirtualPlayer> tabBots = new ArrayList<>();
    private final List<MovingBot> liveBots = new ArrayList<>();
    private BukkitTask ticker;
    private YamlConfiguration bots;

    @Override public void onEnable() {
        saveDefaultConfig(); saveResource("bots.yml", false);
        bots = YamlConfiguration.loadConfiguration(new File(getDataFolder(), "bots.yml"));
        loadBots(); Bukkit.getPluginManager().registerEvents(this, this);
        int period = Math.max(1, getConfig().getInt("settings.movement-period-ticks", 2));
        ticker = Bukkit.getScheduler().runTaskTimer(this, () -> tick(period), 1L, period);
        getLogger().info("Loaded " + tabBots.size() + " TAB and " + liveBots.size() + " live bots.");
    }

    @Override public void onDisable() {
        if (ticker != null) ticker.cancel();
        for (Player viewer : Bukkit.getOnlinePlayers()) {
            tabBots.forEach(bot -> bot.sendRemovePlayerPacket(viewer));
            liveBots.forEach(bot -> { bot.player.tick(Collections.emptySet()); bot.player.sendRemovePlayerPacket(viewer); });
        }
        tabBots.clear(); liveBots.clear();
    }

    @EventHandler public void onJoin(PlayerJoinEvent event) {
        Bukkit.getScheduler().runTaskLater(this, () -> sendTab(event.getPlayer()), 10L);
    }

    @EventHandler(priority = EventPriority.HIGHEST)
    public void onPing(ServerListPingEvent event) {
        if (getConfig().getBoolean("settings.motd-count-enabled", true))
            event.setMaxPlayers(Math.max(event.getMaxPlayers(), Bukkit.getOnlinePlayers().size() + fakeCount() + 1));
        // Bukkit не позволяет менять getNumPlayers; Bungee-модуль должен менять число на proxy.
    }

    @EventHandler(priority = EventPriority.HIGHEST)
    public void onCommand(PlayerCommandPreprocessEvent event) {
        if (!getConfig().getBoolean("settings.override-online-command", true)) return;
        String cmd = event.getMessage().toLowerCase(Locale.ROOT).split(" ")[0];
        if (!cmd.equals("/online") && !cmd.equals("/list")) return;
        event.setCancelled(true);
        int real = Bukkit.getOnlinePlayers().size(), fake = fakeCount();
        event.getPlayer().sendMessage(ChatColor.GREEN + "Онлайн: " + (real + fake) + ChatColor.GRAY + " (реальных: " + real + ", ботов: " + fake + ")");
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
            VirtualPlayer bot = create(c.getString("name", key), c.getInt("ping", 50), c.getString("luckperms-group", "default"));
            tabBots.add(bot); Bukkit.getOnlinePlayers().forEach(bot::sendAddPlayerPacket);
        }
        ConfigurationSection lives = bots.getConfigurationSection("live-bots");
        if (lives != null) for (String key : lives.getKeys(false)) {
            ConfigurationSection c = lives.getConfigurationSection(key); if (c == null) continue;
            try {
                Location spawn = spawn(c.getConfigurationSection("spawn"));
                Point target = point(c.getConfigurationSection("target"), spawn.getWorld());
                VirtualPlayer player = create(c.getString("name", key), c.getInt("ping", 50), c.getString("luckperms-group", "default"));
                player.setPos(vec(spawn)); player.setYaw(spawn.getYaw()); player.setPitch(spawn.getPitch()); player.setSprinting(true); player.setOnGround(true);
                liveBots.add(new MovingBot(player, spawn.getWorld(), target.vector(), c.getDouble("speed-blocks-per-second", 3.8)));
                Bukkit.getOnlinePlayers().forEach(player::sendAddPlayerPacket);
            } catch (RuntimeException ex) { getLogger().warning("Skipped bot " + key + ": " + ex.getMessage()); }
        }
    }

    private VirtualPlayer create(String name, int ping, String group) {
        if (name.isBlank() || name.length() > 16) throw new IllegalArgumentException("name must be 1-16 characters");
        VirtualPlayer p = VirtualPlayer.create(); p.setName(name); p.setLatency(Math.max(0, ping)); p.setGameMode(GameMode.SURVIVAL);
        if (Bukkit.getPluginManager().isPluginEnabled("LuckPerms")) {
            try { LuckPerms lp = LuckPermsProvider.get(); lp.getUserManager().modifyUser(p.getUuid(), user -> user.data().add(InheritanceNode.builder(group).build())); }
            catch (Exception ex) { getLogger().warning("LuckPerms hook failed for " + name + ": " + ex.getMessage()); }
        }
        return p;
    }

    private void tick(int ticks) {
        for (MovingBot b : liveBots) {
            b.move(ticks / 20D);
            b.player.tick(new HashSet<>(b.world.getPlayers()));
        }
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
        final VirtualPlayer player; final World world; final Vec3d target; final double speed; boolean arrived;
        MovingBot(VirtualPlayer p, World w, Vec3d t, double s){player=p;world=w;target=t;speed=Math.max(.1,s);}
        void move(double seconds) {
            if (arrived) return; Vec3d p=player.getPos(); double dx=target.x-p.x,dz=target.z-p.z, horizontal=Math.sqrt(dx*dx+dz*dz), step=speed*seconds;
            if(horizontal<.03){arrived=true;player.setSprinting(false);return;}
            double amount=Math.min(step,horizontal), nx=p.x+dx/horizontal*amount,nz=p.z+dz/horizontal*amount,ny=groundY(nx,p.y,nz);
            if(Double.isNaN(ny)) { player.setSprinting(false); return; }
            player.setSprinting(true); player.setYaw((float)Math.toDegrees(Math.atan2(-dx,dz))); player.setPos(new Vec3d(nx,ny,nz));
        }
        double groundY(double x,double y,double z) {
            if(!getConfig().getBoolean("settings.physics.enabled",true)) return y;
            int bx=(int)Math.floor(x), bz=(int)Math.floor(z), base=(int)Math.floor(y);
            int up=getConfig().getInt("settings.physics.max-step-height",1), down=getConfig().getInt("settings.physics.max-fall-check",4);
            for(int feet=base+up;feet>=base-down;feet--){ Block floor=world.getBlockAt(bx,feet-1,bz), body=world.getBlockAt(bx,feet,bz), head=world.getBlockAt(bx,feet+1,bz); if(!floor.isPassable()&&body.isPassable()&&head.isPassable()) return feet; }
            return Double.NaN;
        }
    }
}
