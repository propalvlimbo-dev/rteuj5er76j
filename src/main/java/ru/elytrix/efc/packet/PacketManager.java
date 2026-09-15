package ru.elytrix.efc.packet;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.checks.movement.TimerA;
import ru.elytrix.efc.data.PlayerData;
import ru.elytrix.efc.util.DamageUtil;

/**
 * Пакетный слой (packetevents 1.8.x, softdepend). Без плагина на сервере
 * тихо отключается — событийные проверки работают как раньше.
 * С плагином: точный счёт Flying для Timer, точный пинг для перемотки,
 * счётчики пакетных взмахов/ударов в /efc debug.
 */
public final class PacketManager {

    private final ElytrixFuckCheats plugin;
    private final Map<UUID, PacketData> data = new ConcurrentHashMap<>();
    private volatile boolean available;

    public PacketManager(ElytrixFuckCheats plugin) {
        this.plugin = plugin;
    }

    public void init() {
        try {
            Class.forName("com.github.retrooper.packetevents.PacketEvents");
        } catch (Throwable missing) {
            plugin.getLogger().info("PacketEvents not found, packet layer disabled.");
            return;
        }
        try {
            PeHook.register(this);
            DamageUtil.setPacketManager(this);
            plugin.getServer().getScheduler().runTaskTimer(plugin, this::evaluate, 20L, 20L);
            available = true;
            plugin.getLogger().info("PacketEvents hooked, packet layer enabled.");
        } catch (Throwable failed) {
            plugin.getLogger().warning("PacketEvents hook failed: " + failed);
        }
    }

    public boolean isAvailable() {
        return available;
    }

    public PacketData get(UUID uuid) {
        return data.computeIfAbsent(uuid, key -> new PacketData());
    }

    /** Точный пинг от PacketEvents (keepalive), -1 если недоступен. */
    public int ping(Player player) {
        if (!available) {
            return -1;
        }
        return PeHook.ping(player);
    }

    /** Netty-поток: движение/поворот. */
    public void flying(Player player, double x, double y, double z,
            float yaw, float pitch, boolean ground, boolean moving, boolean rotating) {
        get(player.getUniqueId()).flying(x, y, z, yaw, pitch, ground, moving, rotating);
    }

    /** Netty-поток: пакет атаки. */
    public void attack(Player player, int entityId) {
        UUID uuid = player.getUniqueId();
        get(uuid).attack(entityId);
        plugin.getDebugCounters().recordPacketAttack(uuid);
    }

    /** Netty-поток: пакет взмаха. */
    public void swing(Player player) {
        UUID uuid = player.getUniqueId();
        get(uuid).swing();
        plugin.getDebugCounters().recordPacketSwing(uuid);
    }

    /**
     * Netty-поток: нарушение пакетной проверки. Сам флаг — в главном потоке
     * через шедулер, exemptions внутри Check.flag работают как обычно.
     */
    public void reportViolation(UUID uuid, String checkId, String details) {
        try {
            plugin.getServer().getScheduler().runTask(plugin, () -> {
                try {
                    Check check = plugin.getCheckManager().get(checkId);
                    PlayerData data = plugin.getDataManager().get(uuid);
                    if (check != null && data != null && data.getPlayer() != null) {
                        check.onPacketViolation(data, details);
                    }
                } catch (Throwable ignored) {
                }
            });
        } catch (Throwable ignored) {
        }
    }

    /** Главный поток, раз в секунду: точный Timer по счёту Flying. */
    private void evaluate() {
        long now = System.currentTimeMillis();
        for (Map.Entry<UUID, PacketData> entry : data.entrySet()) {
            UUID uuid = entry.getKey();
            int count = entry.getValue().pruneAndCountFlying(now);
            if (count > 25) {
                PlayerData playerData = plugin.getDataManager().get(uuid);
                Player player = playerData.getPlayer();
                if (player == null || !player.isOnline()) {
                    data.remove(uuid);
                    continue;
                }
                Check check = plugin.getCheckManager().get("Timer.A");
                if (check instanceof TimerA) {
                    ((TimerA) check).packetFlag(uuid, count + "/s");
                }
            } else if (count == 0) {
                Player player = plugin.getDataManager().get(uuid).getPlayer();
                if (player == null || !player.isOnline()) {
                    data.remove(uuid);
                }
            }
        }
    }
}
