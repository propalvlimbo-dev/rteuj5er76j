package ru.elytrix.efc.grim;

import ac.grim.grimac.GrimAPI;
import ac.grim.grimac.api.config.ConfigManager;
import ac.grim.grimac.checks.Check;
import ac.grim.grimac.checks.impl.breaking.FarBreak;
import ac.grim.grimac.checks.impl.breaking.MultiBreak;
import ac.grim.grimac.checks.impl.breaking.RotationBreak;
import ac.grim.grimac.checks.impl.crash.CrashA;
import ac.grim.grimac.checks.impl.crash.CrashB;
import ac.grim.grimac.checks.impl.crash.CrashC;
import ac.grim.grimac.checks.impl.crash.CrashE;
import ac.grim.grimac.checks.impl.crash.CrashF;
import ac.grim.grimac.checks.impl.crash.CrashH;
import ac.grim.grimac.checks.impl.scaffolding.AirLiquidPlace;
import ac.grim.grimac.checks.impl.scaffolding.FarPlace;
import ac.grim.grimac.checks.impl.scaffolding.MultiPlace;
import ac.grim.grimac.checks.impl.scaffolding.RotationPlace;
import ac.grim.grimac.checks.impl.sprint.SprintA;
import ac.grim.grimac.checks.impl.sprint.SprintD;
import ac.grim.grimac.checks.impl.timer.Timer;
import ac.grim.grimac.checks.impl.timer.TimerLimit;
import ac.grim.grimac.checks.type.BlockBreakCheck;
import ac.grim.grimac.checks.type.BlockPlaceCheck;
import ac.grim.grimac.checks.type.PacketCheck;
import ac.grim.grimac.checks.type.PostPredictionCheck;
import ac.grim.grimac.player.GrimPlayer;
import ac.grim.grimac.utils.anticheat.update.BlockBreak;
import ac.grim.grimac.utils.anticheat.update.BlockPlace;
import ac.grim.grimac.utils.anticheat.update.PredictionComplete;
import ac.grim.grimac.utils.change.BlockModification;
import com.github.retrooper.packetevents.event.PacketReceiveEvent;
import com.github.retrooper.packetevents.protocol.player.GameMode;
import com.github.retrooper.packetevents.protocol.world.BlockFace;
import com.github.retrooper.packetevents.protocol.world.states.type.StateType;
import com.github.retrooper.packetevents.protocol.world.states.type.StateTypes;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Queue;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.Location;
import org.bukkit.block.Block;
import org.bukkit.entity.Player;
import org.bukkit.event.block.BlockBreakEvent;
import org.bukkit.event.block.BlockDamageEvent;
import org.bukkit.event.block.BlockPlaceEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.packet.PacketManager;

/**
 * Мост EFC <-> Grim: состояние GrimPlayer на игрока, 17 Grim-проверок,
 * маршрутизация пакетов/событий, флаги уходят в наказания EFC.
 */
public final class GrimBridge {

    private static ElytrixFuckCheats plugin;
    private static PacketManager packetManager;
    private static volatile boolean packetLayer;

    private static final Map<UUID, GrimState> states = new ConcurrentHashMap<>();
    private static final Map<Check, Link> links = new ConcurrentHashMap<>();

    private GrimBridge() {
    }

    public static void init(ElytrixFuckCheats plugin) {
        GrimBridge.plugin = plugin;
        plugin.getServer().getPluginManager().registerEvents(GrimListener.INSTANCE, plugin);
    }

    public static void setPacketManager(PacketManager manager) {
        packetManager = manager;
    }

    public static void setPacketLayer(boolean available) {
        packetLayer = available;
    }

    public static boolean hasPacketLayer() {
        return packetLayer;
    }

    /** Флаг из Grim-проверки (любой поток): уходит в наказания EFC. */
    public static void report(Check grimCheck, String detail) {
        try {
            Link link = links.get(grimCheck);
            if (link == null || plugin == null) return;
            String clean = detail == null ? "" : detail;
            if (packetManager != null) {
                packetManager.reportViolation(link.state.uuid, link.bridge.id(), clean);
                return;
            }
            final UUID uuid = link.state.uuid;
            final String id = link.bridge.id();
            plugin.getServer().getScheduler().runTask(plugin, () -> {
                try {
                    ru.elytrix.efc.check.Check check = plugin.getCheckManager().get(id);
                    ru.elytrix.efc.data.PlayerData data = plugin.getDataManager().get(uuid);
                    if (check != null && data != null && data.getPlayer() != null) {
                        check.onPacketViolation(data, clean);
                    }
                } catch (Throwable ignored) {
                }
            });
        } catch (Throwable ignored) {
        }
    }

    /** Netty-поток: сырой пакет всем Grim-проверкам. */
    public static void dispatchPacket(PacketReceiveEvent event) {
        Object raw;
        try {
            raw = event.getPlayer();
        } catch (Throwable ignored) {
            return;
        }
        if (!(raw instanceof Player)) return;
        Player player = (Player) raw;
        try {
            GrimState state = state(player);
            sync(state, player);
            for (CheckEntry entry : state.checks) {
                try {
                    if (entry.check instanceof PacketCheck) {
                        ((PacketCheck) entry.check).onPacketReceive(event);
                    }
                } catch (Throwable ignored) {
                }
            }
            if (entryIsFlying(state, event)) {
                endTick(state);
            }
        } catch (Throwable ignored) {
        }
    }

    /** Главный поток: тик движения когда нет пакетного слоя. */
    public static void onBukkitMove(Player player) {
        if (packetLayer) return;
        try {
            GrimState state = state(player);
            sync(state, player);
            endTick(state);
        } catch (Throwable ignored) {
        }
    }

    /** Главный поток: начало ломания блока. */
    public static void onBlockDamage(BlockDamageEvent event) {
        Player player = event.getPlayer();
        Block block = event.getBlock();
        if (player == null || block == null) return;
        try {
            GrimState state = state(player);
            sync(state, player);
            com.github.retrooper.packetevents.util.Vector3i pos =
                    new com.github.retrooper.packetevents.util.Vector3i(block.getX(), block.getY(), block.getZ());
            state.grim.blockHistory.add(new BlockModification(
                    BlockModification.Cause.START_DIGGING, pos,
                    GrimAPI.INSTANCE.getTickManager().currentTick, mapMaterial(block.getType().name())));
            BlockBreak compat = new BlockBreak(
                    com.github.retrooper.packetevents.protocol.player.DiggingAction.START_DIGGING,
                    pos, BlockFace.UP);
            compat.onCancel(() -> event.setCancelled(true));
            for (CheckEntry entry : state.checks) {
                try {
                    if (entry.check instanceof BlockBreakCheck) {
                        ((BlockBreakCheck) entry.check).onBlockBreak(compat);
                    }
                } catch (Throwable ignored) {
                }
            }
            state.pendingBreak.add(compat);
        } catch (Throwable ignored) {
        }
    }

    /** Главный поток: блок доломан. */
    public static void onBlockBreak(BlockBreakEvent event) {
        Player player = event.getPlayer();
        Block block = event.getBlock();
        if (player == null || block == null) return;
        try {
            GrimState state = state(player);
            sync(state, player);
            com.github.retrooper.packetevents.util.Vector3i pos =
                    new com.github.retrooper.packetevents.util.Vector3i(block.getX(), block.getY(), block.getZ());
            BlockBreak compat = new BlockBreak(
                    com.github.retrooper.packetevents.protocol.player.DiggingAction.FINISHED_DIGGING,
                    pos, BlockFace.UP);
            compat.onCancel(() -> event.setCancelled(true));
            for (CheckEntry entry : state.checks) {
                try {
                    if (entry.check instanceof BlockBreakCheck) {
                        ((BlockBreakCheck) entry.check).onBlockBreak(compat);
                    }
                } catch (Throwable ignored) {
                }
            }
            state.pendingBreak.add(compat);
        } catch (Throwable ignored) {
        }
    }

    /** Главный поток: установка блока. */
    public static void onBlockPlace(BlockPlaceEvent event) {
        Player player = event.getPlayer();
        Block against = event.getBlockAgainst();
        Block placed = event.getBlock();
        if (player == null || against == null || placed == null) return;
        try {
            GrimState state = state(player);
            sync(state, player);
            com.github.retrooper.packetevents.util.Vector3i pos =
                    new com.github.retrooper.packetevents.util.Vector3i(against.getX(), against.getY(), against.getZ());
            state.lastAgainstX = against.getX();
            state.lastAgainstY = against.getY();
            state.lastAgainstZ = against.getZ();
            state.lastAgainstType = against.getType().name();
            BlockPlace compat = new BlockPlace(pos, mapMaterial(placed.getType().name()),
                    new com.github.retrooper.packetevents.util.Vector3f(0.5F, 0.5F, 0.5F),
                    mapFace(event.getBlockFace()));
            compat.onResync(() -> event.setCancelled(true));
            for (CheckEntry entry : state.checks) {
                try {
                    if (entry.check instanceof BlockPlaceCheck) {
                        ((BlockPlaceCheck) entry.check).onBlockPlace(compat);
                    }
                } catch (Throwable ignored) {
                }
            }
            state.pendingPlace.add(compat);
        } catch (Throwable ignored) {
        }
    }

    public static void requestSetback(GrimPlayer grimPlayer) {
        try {
            if (plugin == null || grimPlayer == null || grimPlayer.bukkitPlayer == null) return;
            Player target = grimPlayer.bukkitPlayer;
            plugin.getServer().getScheduler().runTask(plugin, () -> {
                try {
                    plugin.getSetbackManager().setback(target);
                } catch (Throwable ignored) {
                }
            });
        } catch (Throwable ignored) {
        }
    }

    public static StateType blockTypeAt(Player player, int x, int y, int z) {
        try {
            if (player != null) {
                GrimState state = states.get(player.getUniqueId());
                if (state != null && state.lastAgainstType != null
                        && state.lastAgainstX == x && state.lastAgainstY == y && state.lastAgainstZ == z) {
                    return mapMaterial(state.lastAgainstType);
                }
            }
        } catch (Throwable ignored) {
        }
        return StateTypes.STONE;
    }

    public static void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    private static boolean entryIsFlying(GrimState state, PacketReceiveEvent event) {
        try {
            return com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientPlayerFlying
                    .isFlying(event.getPacketType());
        } catch (Throwable ignored) {
            return false;
        }
    }

    private static void endTick(GrimState state) {
        GrimAPI.INSTANCE.getTickManager().currentTick++;
        BlockBreak br;
        while ((br = state.pendingBreak.poll()) != null) {
            for (CheckEntry entry : state.checks) {
                try {
                    if (entry.check instanceof BlockBreakCheck) {
                        ((BlockBreakCheck) entry.check).onPostFlyingBlockBreak(br);
                    }
                } catch (Throwable ignored) {
                }
            }
        }
        BlockPlace pl;
        while ((pl = state.pendingPlace.poll()) != null) {
            for (CheckEntry entry : state.checks) {
                try {
                    if (entry.check instanceof BlockPlaceCheck) {
                        ((BlockPlaceCheck) entry.check).onPostFlyingBlockPlace(pl);
                    }
                } catch (Throwable ignored) {
                }
            }
        }
        PredictionComplete complete = new PredictionComplete(true);
        for (CheckEntry entry : state.checks) {
            try {
                if (entry.check instanceof PostPredictionCheck) {
                    ((PostPredictionCheck) entry.check).onPredictionComplete(complete);
                }
            } catch (Throwable ignored) {
            }
        }
    }

    private static GrimState state(Player player) {
        UUID uuid = player.getUniqueId();
        GrimState existing = states.get(uuid);
        if (existing != null) {
            existing.grim.bukkitPlayer = player;
            return existing;
        }
        GrimState created = new GrimState(uuid, player);
        GrimState raced = states.putIfAbsent(uuid, created);
        return raced == null ? created : raced;
    }

    private static void sync(GrimState state, Player player) {
        GrimPlayer grim = state.grim;
        try {
            Location loc = player.getLocation();
            grim.lastYaw = state.prevYaw;
            grim.lastPitch = state.prevPitch;
            grim.x = loc.getX();
            grim.y = loc.getY();
            grim.z = loc.getZ();
            grim.yaw = loc.getYaw();
            grim.pitch = loc.getPitch();
            state.prevYaw = loc.getYaw();
            state.prevPitch = loc.getPitch();
        } catch (Throwable ignored) {
        }
        try {
            grim.food = player.getFoodLevel();
        } catch (Throwable ignored) {
        }
        try {
            grim.isSprinting = player.isSprinting();
        } catch (Throwable ignored) {
        }
        try {
            grim.canFly = player.getAllowFlight();
        } catch (Throwable ignored) {
        }
        try {
            grim.gamemode = mapGameMode(player.getGameMode().name());
        } catch (Throwable ignored) {
        }
        try {
            grim.setInVehicle(player.isInsideVehicle());
        } catch (Throwable ignored) {
        }
        try {
            int ping = packetManager == null ? -1 : packetManager.ping(player);
            grim.setPingMillis(ping < 0 ? 50 : ping);
        } catch (Throwable ignored) {
        }
    }

    private static GameMode mapGameMode(String name) {
        if ("CREATIVE".equals(name)) return GameMode.CREATIVE;
        if ("ADVENTURE".equals(name)) return GameMode.ADVENTURE;
        if ("SPECTATOR".equals(name)) return GameMode.SPECTATOR;
        return GameMode.SURVIVAL;
    }

    private static BlockFace mapFace(org.bukkit.block.BlockFace face) {
        if (face == null) return BlockFace.UP;
        switch (face) {
            case DOWN: return BlockFace.DOWN;
            case NORTH: return BlockFace.NORTH;
            case SOUTH: return BlockFace.SOUTH;
            case WEST: return BlockFace.WEST;
            case EAST: return BlockFace.EAST;
            case UP:
            default: return BlockFace.UP;
        }
    }

    private static StateType mapMaterial(String name) {
        if (name == null) return StateTypes.STONE;
        if (name.contains("AIR")) return StateTypes.AIR;
        if (name.contains("WATER")) return StateTypes.WATER;
        if (name.contains("LAVA")) return StateTypes.LAVA;
        if (name.contains("BUBBLE")) return StateTypes.BUBBLE_COLUMN;
        if (name.contains("SCAFFOLDING")) return StateTypes.SCAFFOLDING;
        if (name.contains("FIRE")) return StateTypes.FIRE;
        if (name.contains("REDSTONE_WIRE")) return StateTypes.REDSTONE_WIRE;
        return StateTypes.STONE;
    }

    private static final class Link {
        final GrimState state;
        final GrimBridgeCheck bridge;

        Link(GrimState state, GrimBridgeCheck bridge) {
            this.state = state;
            this.bridge = bridge;
        }
    }

    private static final class CheckEntry {
        final Check check;

        CheckEntry(Check check) {
            this.check = check;
        }
    }

    private static final class GrimState {
        final UUID uuid;
        final GrimPlayer grim;
        final List<CheckEntry> checks = new ArrayList<>();
        final Queue<BlockBreak> pendingBreak = new ArrayDeque<>();
        final Queue<BlockPlace> pendingPlace = new ArrayDeque<>();
        float prevYaw;
        float prevPitch;
        int lastAgainstX;
        int lastAgainstY;
        int lastAgainstZ;
        String lastAgainstType;

        GrimState(UUID uuid, Player player) {
            this.uuid = uuid;
            this.grim = new GrimPlayer(player);
            ConfigManager config = new ConfigManager();
            add(new CrashA(grim), "Crash.A", config);
            add(new CrashB(grim), "Crash.B", config);
            add(new CrashC(grim), "Crash.C", config);
            add(new CrashE(grim), "Crash.E", config);
            add(new CrashF(grim), "Crash.F", config);
            add(new CrashH(grim), "Crash.H", config);
            add(new Timer(grim), "Timer.Grim", config);
            add(new TimerLimit(grim), "Timer.Limit", config);
            add(new SprintA(grim), "Sprint.A", config);
            add(new SprintD(grim), "Sprint.D", config);
            add(new MultiBreak(grim), "Nuker.B", config);
            add(new FarBreak(grim), "FarBreak.B", config);
            add(new RotationBreak(grim), "RotationBreak.B", config);
            add(new MultiPlace(grim), "MultiPlace.A", config);
            add(new FarPlace(grim), "FarPlace.B", config);
            add(new RotationPlace(grim), "RotationPlace.B", config);
            add(new AirLiquidPlace(grim), "InvalidPlace.B", config);
        }

        private void add(Check check, String efcId, ConfigManager config) {
            try {
                check.onReload(config);
            } catch (Throwable ignored) {
            }
            checks.add(new CheckEntry(check));
            try {
                if (plugin != null && plugin.getCheckManager() != null) {
                    ru.elytrix.efc.check.Check found = plugin.getCheckManager().get(efcId);
                    if (found instanceof GrimBridgeCheck) {
                        links.put(check, new Link(this, (GrimBridgeCheck) found));
                    }
                }
            } catch (Throwable ignored) {
            }
        }
    }
}
