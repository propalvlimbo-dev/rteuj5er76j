package ru.elytrix.efc.checks.combat;

import org.bukkit.Location;
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
 * HitBox.A: тихий блок расширенных хитбоксов.
 * Луч обязан пересекать бокс +0.3 м: промах — удар в воздух,
 * который дошёл только благодаря расширителю. Алертов, VL и кика
 * нет (хитбоксы отданы Intave) — только отмена урона.
 * Отмена двойная: флаг cancel + урон в 0 через рефлексию,
 * так как кривые форки иногда игнорируют cancel.
 * Полный аналог Grim — отмена пакета атаки; здесь уровень Bukkit.
 */
public final class HitBoxA extends Check {

    public HitBoxA(ElytrixFuckCheats plugin) {
        super(plugin, "HitBox", "A", Category.COMBAT);
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        if (!isEnabled()) {
            return;
        }
        Player attacker = DamageUtil.meleeAttacker(event);
        if (attacker == null) {
            return;
        }
        Entity rawVictim = DamageUtil.entityOf(event);
        if (!(rawVictim instanceof Player)) {
            return;
        }
        Player victim = (Player) rawVictim;
        long now = System.currentTimeMillis();
        Location past = plugin.getPositionHistory().locationAt(
                attacker, now - DamageUtil.attackerDelay(attacker));
        Location eye = new Location(past.getWorld(), past.getX(),
                past.getY() + 1.62, past.getZ(), past.getYaw(), past.getPitch());
        Location feet = plugin.getPositionHistory().locationAt(
                victim, now - DamageUtil.rewindDelay(attacker, victim));
        if (CombatGeometry.eyeToBoxDistance(eye, feet, 0.1) > 8.0) {
            return;
        }
        boolean hit = CombatGeometry.rayHitsBoxDir(
                eye.toVector(), eye.getDirection(), feet, 0.3, 8.0);
        if (!hit) {
            event.setCancelled(true);
            DamageUtil.setDamage(event, 0.0);
        }
    }
}
