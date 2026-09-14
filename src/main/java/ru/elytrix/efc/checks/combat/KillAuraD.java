package ru.elytrix.efc.checks.combat;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.DamageUtil;

/**
 * KillAura.D: KeepSprint (порт Medusa KillAuraB).
 * Честный удар в спринте сбивает скорость, чит бежит как по рельсам:
 * ускорение &lt; 0.0025 при скорости &gt; 0.22 в спринте сразу после удара.
 * Пороги Medusa один в один; сверху наш гейт — 20 таких тиков подряд,
 * чтобы разовый ровный бег честного не флагал. Полёт/элитра/транспорт — мимо.
 */
public final class KillAuraD extends Check {

    private static final class State {
        double lastDxz;
        boolean has;
        int streak;
        long lastVictim;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public KillAuraD(ElytrixFuckCheats plugin) {
        super(plugin, "KillAura", "D", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        if (player.isGliding() || player.isInsideVehicle() || player.getAllowFlight()) {
            return;
        }
        State state = states.computeIfAbsent(player.getUniqueId(), key -> new State());
        double dx = event.getTo().getX() - event.getFrom().getX();
        double dz = event.getTo().getZ() - event.getFrom().getZ();
        double dxz = Math.sqrt(dx * dx + dz * dz);
        if (!state.has) {
            state.has = true;
            state.lastDxz = dxz;
            return;
        }
        double accel = Math.abs(dxz - state.lastDxz);
        state.lastDxz = dxz;

        long now = System.currentTimeMillis();
        boolean invalid = accel < 0.0025
                && dxz > 0.22
                && player.isSprinting()
                && now - plugin.getDataManager().get(player).getLastAttack() < 250
                && now - state.lastVictim < 1000;
        if (invalid) {
            if (++state.streak >= 20) {
                state.streak = 0;
                flag(plugin.getDataManager().get(player), "keepsprint");
            }
        } else {
            state.streak = 0;
        }
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        Player attacker = DamageUtil.meleeAttacker(event);
        if (attacker == null) {
            return;
        }
        Entity victim = DamageUtil.entityOf(event);
        if (victim instanceof Player) {
            states.computeIfAbsent(attacker.getUniqueId(), key -> new State())
                    .lastVictim = System.currentTimeMillis();
        }
    }
}
