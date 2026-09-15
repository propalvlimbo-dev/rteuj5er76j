package ru.elytrix.efc.checks.movement;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.Material;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.event.player.PlayerVelocityEvent;
import org.bukkit.potion.PotionEffectType;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.MovementUtil;

/**
 * NoFall.B: падение глубже 6 блоков без урона.
 * Урон доказывается фреймами неуязвимости (getNoDamageTicks) — работает
 * на любом форке, даже где сломан getCause у EntityDamageEvent.
 * Долгий простой после приземления сбрасывает подозрение без флага:
 * урон мог прийти и уйти, пока игрок стоял.
 */
public final class NoFallB extends Check {

    private final Map<UUID, Double> fallStart = new ConcurrentHashMap<>();
    private final Map<UUID, Double> pendingDrop = new ConcurrentHashMap<>();
    private final Map<UUID, Long> pendingTime = new ConcurrentHashMap<>();
    private final Map<UUID, Long> lastEval = new ConcurrentHashMap<>();
    private final Map<UUID, Long> lastCantCheck = new ConcurrentHashMap<>();

    public NoFallB(ElytrixFuckCheats plugin) {
        super(plugin, "NoFall", "B", Category.MOVEMENT);
    }

    @Override
    public void onQuit(UUID uuid) {
        fallStart.remove(uuid);
        pendingDrop.remove(uuid);
        pendingTime.remove(uuid);
        lastEval.remove(uuid);
        lastCantCheck.remove(uuid);
    }

    @EventHandler
    public void onVelocity(PlayerVelocityEvent event) {
        try {
            MovementUtil.noteVelocity(event.getPlayer().getUniqueId());
        } catch (Throwable ignored) {
        }
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        if (player == null || event.getTo() == null) {
            return;
        }
        UUID id = player.getUniqueId();
        long now = System.currentTimeMillis();
        if (MovementUtil.cantCheck(player) || MovementUtil.velocityRecent(id)) {
            clear(id);
            lastCantCheck.put(id, now);
            return;
        }
        if (!player.isOnGround()) {
            double y = event.getTo().getY();
            Double start = fallStart.get(id);
            if (start == null || y > start) {
                fallStart.put(id, y);
            }
            evalPending(player, id, now);
            return;
        }
        // Земля. Свежий выход из полёта/транспорта/элитр — не судим приземление.
        Long exemptEnd = lastCantCheck.get(id);
        if (exemptEnd != null && now - exemptEnd < 3000) {
            clear(id);
            return;
        }
        double y = event.getTo().getY();
        Double start = fallStart.remove(id);
        double drop = start == null ? 0 : start - y;
        if (softLanding(player)) {
            pendingDrop.remove(id);
            pendingTime.remove(id);
            return;
        }
        if (drop > 6.0 && !pendingDrop.containsKey(id)) {
            pendingDrop.put(id, drop);
            pendingTime.put(id, now);
        }
        evalPending(player, id, now);
    }

    private void evalPending(Player player, UUID id, long now) {
        Double drop = pendingDrop.get(id);
        if (drop == null) {
            return;
        }
        Long prev = lastEval.get(id);
        lastEval.put(id, now);
        if (prev != null && now - prev > 1500) {
            // Игрок стоял без движения — урон мог прийти и уйти. Не судим.
            pendingDrop.remove(id);
            pendingTime.remove(id);
            return;
        }
        int noDamageTicks = 0;
        try {
            noDamageTicks = player.getNoDamageTicks();
        } catch (Throwable ignored) {
        }
        if (noDamageTicks > 0) {
            pendingDrop.remove(id);
            pendingTime.remove(id);
            return;
        }
        long age = now - pendingTime.getOrDefault(id, now);
        if (age > 1500) {
            pendingDrop.remove(id);
            pendingTime.remove(id);
            flag(plugin.getDataManager().get(player), String.format("drop=%.1f", drop));
        }
    }

    private void clear(UUID id) {
        fallStart.remove(id);
        pendingDrop.remove(id);
        pendingTime.remove(id);
        lastEval.remove(id);
    }

    private static boolean softLanding(Player player) {
        Material feet = MovementUtil.feetType(player);
        Material below = MovementUtil.belowType(player);
        if (MovementUtil.isLiquid(feet) || MovementUtil.isLiquid(below)) {
            return true;
        }
        if (MovementUtil.isWeb(feet) || MovementUtil.isWeb(below)) {
            return true;
        }
        if (MovementUtil.isClimbable(feet) || MovementUtil.isClimbable(below)) {
            return true;
        }
        if (MovementUtil.isBounceSafe(feet) || MovementUtil.isBounceSafe(below)) {
            return true;
        }
        if (MovementUtil.isSlowGround(below)) {
            return true;
        }
        if (MovementUtil.effectAmplifier(player, PotionEffectType.LEVITATION) >= 0
                || MovementUtil.effectAmplifier(player, PotionEffectType.SLOW_FALLING) >= 0) {
            return true;
        }
        return false;
    }
}
