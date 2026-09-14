package ru.elytrix.efc.data;

import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.util.DamageUtil;

/** Фиксирует момент последнего удара — им гейтятся Aim-проверки. */
public final class CombatTracker implements Listener {

    private final ElytrixFuckCheats plugin;

    public CombatTracker(ElytrixFuckCheats plugin) {
        this.plugin = plugin;
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        Player attacker = DamageUtil.meleeAttacker(event);
        if (attacker == null) {
            return;
        }
        plugin.getDataManager().get(attacker).setLastAttack(System.currentTimeMillis());
    }
}
