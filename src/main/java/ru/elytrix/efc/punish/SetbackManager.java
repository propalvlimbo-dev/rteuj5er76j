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
import ru.elytrix.efc.util.MovementUtil;

/**
 * Сетбэк как у Grim: возврат на последнюю твёрдую точку.
 * Check.flag дёргает setback за любое движение-нарушение —
 * читер резинится вместо свободного полёта.
 * Портировано из Grim (GPL-3.0), адаптировано под Bukkit.
 */
public final class SetbackManager implements Listener {

    private final ElytrixFuckCheats plugin;
    private final Map<UUID, Location> safe = new ConcurrentHashMap<>();
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
        boolean ground;
        try {
            ground = player.isOnGround();
        } catch (Throwable ignored) {
            return;
        }
        if (!ground || MovementUtil.cantCheck(player)) {
            return;
        }
        Location to = event.getTo();
        try {
            safe.put(player.getUniqueId(),
                    new Location(to.getWorld(), to.getX(), to.getY(), to.getZ()));
        } catch (Throwable ignored) {
        }
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        try {
            UUID uuid = event.getPlayer().getUniqueId();
            safe.remove(uuid);
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
            Location point = safe.get(player.getUniqueId());
            if (point == null) {
                return;
            }
            ownTeleport.put(player.getUniqueId(), System.currentTimeMillis());
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
