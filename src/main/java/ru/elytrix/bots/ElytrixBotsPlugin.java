package ru.elytrix.bots;

import dev.by1337.virtualentity.api.virtual.player.VirtualPlayer;
import org.bukkit.Bukkit;
import org.bukkit.GameMode;
import org.bukkit.World;
import org.bukkit.configuration.ConfigurationSection;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.scheduler.BukkitTask;
import org.by1337.blib.geom.Vec3d;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public final class ElytrixBotsPlugin extends JavaPlugin implements Listener {
    private final List<VirtualPlayer> tabBots = new ArrayList<>();
    private final List<MovingBot> liveBots = new ArrayList<>();
    private BukkitTask ticker;

    @Override
    public void onEnable() {
        saveDefaultConfig();
        loadBots();
        Bukkit.getPluginManager().registerEvents(this, this);

        int period = Math.max(1, getConfig().getInt("settings.movement-period-ticks", 2));
        ticker = Bukkit.getScheduler().runTaskTimer(this, () -> tick(period), 1L, period);
        getLogger().info("Started " + tabBots.size() + " TAB bots and " + liveBots.size() + " live packet bots.");
    }

    @Override
    public void onDisable() {
        if (ticker != null) ticker.cancel();
        Set<Player> nobody = Collections.emptySet();
        liveBots.forEach(bot -> bot.player.tick(nobody));
        for (Player viewer : Bukkit.getOnlinePlayers()) {
            tabBots.forEach(bot -> bot.sendRemovePlayerPacket(viewer));
        }
        tabBots.clear();
        liveBots.clear();
    }

    @EventHandler
    public void onJoin(PlayerJoinEvent event) {
        Player viewer = event.getPlayer();
        // Клиент должен полностью завершить вход перед получением player-info пакетов.
        Bukkit.getScheduler().runTaskLater(this, () -> {
            if (!viewer.isOnline()) return;
            tabBots.forEach(bot -> bot.sendAddPlayerPacket(viewer));
        }, 10L);
    }

    private void loadBots() {
        for (var raw : getConfig().getMapList("tab-bots")) {
            String name = String.valueOf(raw.get("name"));
            VirtualPlayer bot = createPlayer(name, intValue(raw.get("ping"), 50));
            tabBots.add(bot);
            Bukkit.getOnlinePlayers().forEach(bot::sendAddPlayerPacket);
        }

        ConfigurationSection section = getConfig().getConfigurationSection("live-bots");
        if (section == null) return;
        for (String key : section.getKeys(false)) {
            ConfigurationSection cfg = section.getConfigurationSection(key);
            if (cfg == null) continue;
            try {
                String name = cfg.getString("name", key);
                Point spawn = point(cfg.getConfigurationSection("spawn"), true);
                Point target = point(cfg.getConfigurationSection("target"), false);
                if (spawn.world != target.world) throw new IllegalArgumentException("spawn and target worlds differ");

                VirtualPlayer player = createPlayer(name, cfg.getInt("ping", 50));
                player.setPos(spawn.vector());
                player.setYaw(spawn.yaw);
                player.setPitch(spawn.pitch);
                player.setSprinting(true);
                player.setOnGround(true);
                liveBots.add(new MovingBot(player, spawn.world, target.vector(), cfg.getDouble("speed-blocks-per-second", 3.8)));
            } catch (RuntimeException ex) {
                getLogger().warning("Skipped live bot '" + key + "': " + ex.getMessage());
            }
        }
    }

    private VirtualPlayer createPlayer(String name, int ping) {
        if (name.isBlank() || name.length() > 16) throw new IllegalArgumentException("bot name must contain 1-16 characters");
        VirtualPlayer player = VirtualPlayer.create();
        player.setName(name);
        player.setLatency(Math.max(0, ping));
        player.setGameMode(GameMode.SURVIVAL);
        return player;
    }

    private void tick(int periodTicks) {
        for (MovingBot bot : liveBots) {
            bot.move(periodTicks / 20.0);
            // Только реальные зрители того же мира; никаких Player-сессий у ботов нет.
            Set<Player> viewers = new HashSet<>(bot.world.getPlayers());
            bot.player.tick(viewers);
        }
    }

    private Point point(ConfigurationSection cfg, boolean rotation) {
        if (cfg == null) throw new IllegalArgumentException("missing point");
        World world = Bukkit.getWorld(cfg.getString("world", "world"));
        if (world == null) throw new IllegalArgumentException("world not found: " + cfg.getString("world"));
        return new Point(world, cfg.getDouble("x"), cfg.getDouble("y"), cfg.getDouble("z"),
                rotation ? (float) cfg.getDouble("yaw") : 0F, rotation ? (float) cfg.getDouble("pitch") : 0F);
    }

    private static int intValue(Object value, int fallback) {
        if (value instanceof Number) return ((Number) value).intValue();
        try { return Integer.parseInt(String.valueOf(value)); } catch (Exception ignored) { return fallback; }
    }

    private record Point(World world, double x, double y, double z, float yaw, float pitch) {
        Vec3d vector() { return new Vec3d(x, y, z); }
    }

    private static final class MovingBot {
        private final VirtualPlayer player;
        private final World world;
        private final Vec3d target;
        private final double speed;
        private boolean arrived;

        private MovingBot(VirtualPlayer player, World world, Vec3d target, double speed) {
            this.player = player;
            this.world = world;
            this.target = target;
            this.speed = Math.max(0.1, speed);
        }

        private void move(double seconds) {
            if (arrived) return;
            Vec3d pos = player.getPos();
            double dx = target.x - pos.x, dy = target.y - pos.y, dz = target.z - pos.z;
            double distance = Math.sqrt(dx * dx + dy * dy + dz * dz);
            double step = speed * seconds;
            if (distance <= step || distance < 0.02) {
                player.setPos(target);
                player.setSprinting(false);
                arrived = true;
                return;
            }
            player.setYaw((float) Math.toDegrees(Math.atan2(-dx, dz)));
            player.setPos(new Vec3d(pos.x + dx / distance * step, pos.y + dy / distance * step, pos.z + dz / distance * step));
        }
    }
}
