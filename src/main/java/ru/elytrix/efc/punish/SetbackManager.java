package ru.elytrix.efc.punish;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.Location;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import ru.elytrix.efc.ElytrixFuckCheats;

/**
 * Сетбэк как у Grim: резина на предыдущую свежую точку.
 * Check.flag дёргает setback за любое движение-нарушение —
 * читер стоит на месте, пока не выключит функцию или не кикнет.
 * Точка только свежее 3 сек и в том же мире: «не пойми куда»
 * тепать больше не может. Предыдущая (а не текущая), чтобы резина
 * работала при любом порядке слушателей движения.
 */
public final class SetbackManager implements Listener {

    private final ElytrixFuckCheats plugin;
    private final Map<UUID, Location> last = new ConcurrentHashMap<>();
    private final Map<UUID, Location> prev = new ConcurrentHashMap<>();
    private final Map<UUID, Long> lastTime = new ConcurrentHashMap<>();
    private final Map<UUID, Long> ownTeleport = new ConcurrentHashMap<>();

    public SetbackManager(ElytrixFuckCheats plugin) {
        this.plugin = plugin;
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        if (player == null || event.getTo() == null) {
            return;
        }
        Location to = event.getTo();
        try {
            UUID uuid = player.getUniqueId();
            Location old = last.get(uuid);
            if (old != null) {
                prev.put(uuid, old);
            }
            last.put(uuid, new Location(to.getWorld(), to.getX(), to.getY(), to.getZ()));
            lastTime.put(uuid, System.currentTimeMillis());
        } catch (Throwable ignored) {
        }
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        try {
            UUID uuid = event.getPlayer().getUniqueId();
            last.remove(uuid);
            prev.remove(uuid);
            lastTime.remove(uuid);
            ownTeleport.remove(uuid);
        } catch (Throwable ignored) {
        }
    }

    /** Резиновый телепорт на точку. */
    public void setback(Player player) {
        if (player == null) {
            return;
        }
        try {
            UUID uuid = player.getUniqueId();
            Location point = prev.get(uuid);
            if (point == null) {
                point = last.get(uuid);
            }
            Long time = lastTime.get(uuid);
            if (point == null || point.getWorld() == null || time == null
                    || System.currentTimeMillis() - time > 3000
                    || !point.getWorld().equals(player.getLocation().getWorld())) {
                return;
            }
            ownTeleport.put(uuid, System.currentTimeMillis());
            player.teleport(point);
        } catch (Throwable ignored) {
            try {
                ownTeleport.remove(player.getUniqueId());
            } catch (Throwable ignoredAgain) {
            }
        }
    }

    /** Это был наш сетбэк-телепорт? (гасит грейс телепорта у ExemptionManager) */
    public boolean consumeOwnTeleport(UUID uuid) {
        return ownTeleport.remove(uuid) != null;
    }
}
