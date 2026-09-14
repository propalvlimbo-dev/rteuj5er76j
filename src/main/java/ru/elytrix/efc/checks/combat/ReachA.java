package ru.elytrix.efc.checks.combat;

import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Reach.A: удар с невозможной дистанции.
 * Честный предел 1.16 — 3.0 блока + лаг. Порог 3.6 ловит только наглых.
 */
public final class ReachA extends Check {

    public ReachA(ElytrixFuckCheats plugin) {
        super(plugin, "Reach", "A", Category.COMBAT);
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        if (!(event.getDamager() instanceof Player)) {
            return;
        }
        Player attacker = (Player) event.getDamager();
        Entity victim = event.getEntity();
        double distance = attacker.getLocation().distance(victim.getLocation());
        double max = cfg("max-reach", 3.6);
        if (distance > max) {
            flag(plugin.getDataManager().get(attacker), "dist " + String.format("%.2f", distance));
        }
    }
}
