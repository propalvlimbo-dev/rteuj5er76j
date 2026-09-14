package ru.elytrix.efc.util;

import org.bukkit.entity.Player;
import org.bukkit.event.entity.DamageCause;
import org.bukkit.event.entity.EntityDamageByEntityEvent;

/** Общие хелперы боевых проверок. */
public final class DamageUtil {

    private DamageUtil() {
    }

    /** Настоящий удар мечом/рукой (не шипы, магия, стрелы, свип мимо). */
    public static boolean isMelee(EntityDamageByEntityEvent event) {
        DamageCause cause = event.getCause();
        return cause == DamageCause.ENTITY_ATTACK || cause == DamageCause.ENTITY_SWEEP_ATTACK;
    }

    /** Атакующий-игрок ближнего боя, иначе null. */
    public static Player meleeAttacker(EntityDamageByEntityEvent event) {
        if (!isMelee(event)) {
            return null;
        }
        if (!(event.getDamager() instanceof Player)) {
            return null;
        }
        return (Player) event.getDamager();
    }
}
