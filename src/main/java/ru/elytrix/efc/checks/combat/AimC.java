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
 * Aim.C: удар мимо взгляда (порт Hawk EntityInteractDirection).
 * Луч из глаза должен пересекать хитбокс жертвы, иначе это доводка.
 * У Hawk расширение бокса 0.2 + лаг-компенсация; у нас пока нет перемотки,
 * поэтому расширение растёт с пингом (та же идея, что в Reach).
 * Только игроки — по мобам нет точных боксов.
 */
public final class AimC extends Check {

    public AimC(ElytrixFuckCheats plugin) {
        super(plugin, "Aim", "C", Category.COMBAT);
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
        Player victim = (Player) rawVictim;
        if (CombatGeometry.eyeToBoxDistance(attacker, victim, 0.1) > 7.0) {
            return;
        }
        int ping = DamageUtil.pingOf(attacker) + DamageUtil.pingOf(victim);
        double expand = Math.min(cfg("base-expand", 0.3) + ping * cfg("per-ms", 0.004),
                cfg("cap-expand", 1.2));
        if (!CombatGeometry.rayHitsBox(attacker, victim, expand, 7.0)) {
            flag(plugin.getDataManager().get(attacker), "direction");
        }
    }
}
