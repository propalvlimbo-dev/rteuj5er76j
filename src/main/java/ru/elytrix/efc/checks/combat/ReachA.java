package ru.elytrix.efc.checks.combat;

import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.CombatGeometry;
import ru.elytrix.efc.util.DamageUtil;

/**
 * Reach.A: дистанция глаз-&gt;хитбокс (порт Hawk EntityInteractReach).
 * База 3.03 м + компенсация пинга. Удар за лимитом СРАЗУ отменяется,
 * как у Grim: запредельный хит не наносит урона. Только игроки.
 */
public final class ReachA extends Check {

    public ReachA(ElytrixFuckCheats plugin) {
        super(plugin, "Reach", "A", Category.COMBAT);
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        Player attacker = DamageUtil.meleeAttacker(event);
        if (attacker == null) {
            return;
        }
        Entity rawVictim = DamageUtil.entityOf(event);
        if (!(rawVictim instanceof Player)) {
            return;
        }
        if (plugin.getExemptionManager().isExempt(attacker, getCategory())) {
            return;
        }
        try {
            if (event.isCancelled()) {
                return;
            }
        } catch (Throwable ignored) {
            return;
        }
        Player victim = (Player) rawVictim;
        double distance = CombatGeometry.eyeToBoxDistance(attacker, victim, 0.1);
        double limit = DamageUtil.reachLimit(attacker, victim,
                cfg("base", 3.03), cfg("per-ms", 0.0022), cfg("cap", 3.75));
        if (distance > limit) {
            flag(plugin.getDataManager().get(attacker),
                    "dist " + String.format("%.2f", distance)
                            + ">" + String.format("%.2f", limit) + " blocked");
            try {
                event.setCancelled(true);
            } catch (Throwable ignored) {
                // Форк без отмены урона — хотя бы флаг останется.
            }
        }
    }
}
