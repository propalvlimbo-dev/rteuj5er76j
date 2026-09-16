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

    @Override public void onEnable() {
        saveDefaultConfig(); saveResource("bots.yml", false);
        bots = YamlConfiguration.loadConfiguration(new File(getDataFolder(), "bots.yml"));
        datasets = new DatasetManager(this);
        loadBots(); Bukkit.getPluginManager().registerEvents(this, this);
        Objects.requireNonNull(getCommand("elytrixbots")).setExecutor(this);
        int period = Math.max(1, getConfig().getInt("settings.movement-period-ticks", 2));
        ticker = Bukkit.getScheduler().runTaskTimer(this, () -> tick(period), 1L, period);
        getLogger().info("Loaded " + tabBots.size() + " TAB and " + liveBots.size() + " live bots.");
    }

    @Override public void onDisable() {
        if (ticker != null) ticker.cancel();
        for (Player viewer : realPlayers()) {
            tabBots.forEach(bot -> bot.sendRemovePlayerPacket(viewer));
            liveBots.forEach(bot -> { bot.player.tick(Collections.emptySet()); bot.player.sendRemovePlayerPacket(viewer); });
        }
        teams.clear();
        tabBots.clear(); liveBots.clear();
    }

    @EventHandler public void onJoin(PlayerJoinEvent event) {
        Bukkit.getScheduler().runTaskLater(this, () -> sendTab(event.getPlayer()), 10L);
    }

    @EventHandler(priority = EventPriority.HIGHEST)
    public void onPing(ServerListPingEvent event) {
        if (getConfig().getBoolean("settings.motd-count-enabled", true))
            event.setMaxPlayers(20000 + fakeCount());
        // Bukkit не позволяет менять getNumPlayers; Bungee-модуль должен менять число на proxy.
    }

    @EventHandler(priority = EventPriority.HIGHEST)
    public void onCommand(PlayerCommandPreprocessEvent event) {
        if (!getConfig().getBoolean("settings.override-online-command", true)) return;
        String cmd = event.getMessage().toLowerCase(Locale.ROOT).split(" ")[0];
        if (!cmd.equals("/online") && !cmd.equals("/list")) return;
        event.setCancelled(true);
        int real = realPlayers().size(), fake = fakeCount();
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
                player.setPos(vec(spawn)); player.setYaw(spawn.getYaw()); player.setPitch(spawn.getPitch()); player.setSprinting(true); player.setOnGround(true);
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
                net.luckperms.api.model.group.Group lpGroup = lp.getGroupManager().getGroup(group);
                String prefix = lpGroup == null ? null : lpGroup.getCachedData().getMetaData().getPrefix();
                if (prefix != null) {
                    String label = ChatColor.translateAlternateColorCodes('&', prefix) + name;
                    p.setDisplayName(LegacyComponentSerializer.legacySection().deserialize(label));
                    p.setCustomName(LegacyComponentSerializer.legacySection().deserialize(label));
                    p.setCustomNameVisible(true);
                }
            } catch (Exception ex) { getLogger().warning("LuckPerms hook failed for " + name + ": " + ex.getMessage()); }
        }
        teams.add(name, group);
        return p;
    }

    private List<Player> realPlayers() {
        List<Player> result = new ArrayList<>();
        result.addAll(Bukkit.getOnlinePlayers());
        return result;
    }

    private void tick(int ticks) {
        datasets.tick();
        for (MovingBot b : liveBots) {
            b.move(ticks / 20D);
            Set<Player> viewers = new HashSet<>();
            viewers.addAll(b.world.getPlayers());
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
        final VirtualPlayer player; final World world; final Vec3d target; final double speed; boolean arrived; double verticalVelocity;
        MovingBot(VirtualPlayer p, World w, Vec3d t, double s){player=p;world=w;target=t;speed=Math.max(.1,s);}
        void move(double seconds) {
            if (arrived) return; Vec3d p=player.getPos(); double dx=target.x-p.x,dz=target.z-p.z, horizontal=Math.sqrt(dx*dx+dz*dz), step=speed*seconds;
            if(horizontal<.03){arrived=true;player.setSprinting(false);return;}
            double amount=Math.min(step,horizontal), nx=p.x+dx/horizontal*amount,nz=p.z+dz/horizontal*amount;
            boolean obstacle=!world.getBlockAt((int)Math.floor(nx),(int)Math.floor(p.y),(int)Math.floor(nz)).isPassable();
            DatasetManager.MotionSample learned=datasets.imitate(obstacle, random);
            if (learned != null) {
                player.setShiftKeyDown(learned.sneak);
                player.setSprinting(learned.sprint);
                player.setYaw(player.getYaw() + learned.yawDelta * 0.15F);
                if (obstacle && learned.vertical > 0.01) verticalVelocity=Math.max(verticalVelocity, Math.min(5.2, learned.vertical/seconds));
            }
            double ground=groundY(nx,p.y,nz);
            if(Double.isNaN(ground)) { player.setSprinting(false); return; }
            double ny;
            if (ground > p.y + 0.05) {
                verticalVelocity = Math.max(verticalVelocity, learned != null && learned.vertical > 0 ? Math.min(5.2, learned.vertical/seconds) : 4.2);
                ny = Math.min(ground, p.y + verticalVelocity * seconds);
            } else if (ground < p.y - 0.05) { // плавное падение с обычным ускорением
                verticalVelocity = Math.max(-7.0, verticalVelocity - 9.8 * seconds);
                ny = Math.max(ground, p.y + verticalVelocity * seconds);
            } else { ny = ground; verticalVelocity = 0; }
            player.setOnGround(Math.abs(ny-ground)<0.02);
            if (learned == null) player.setSprinting(true);
            float targetYaw=(float)Math.toDegrees(Math.atan2(-dx,dz));
            player.setYaw(targetYaw + (learned == null ? 0 : learned.yawDelta * 0.15F));
            player.setPos(new Vec3d(nx,ny,nz));
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
