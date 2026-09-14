package ru.elytrix.efc.checks.combat;

import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.DamageUtil;

/**
 * Criticals.A: фейковые криты (порт NESS Criticals).
 * Чит подменяет флаг «на земле», чтобы каждый удар был критом.
 * Сигнатура NESS: клиент говорит «в воздухе», а Y ровно целый.
 * Паутина, вода и полёт исключены — там Y врёт и у честных.
 */
public final class CriticalsA extends Check {

    public CriticalsA(ElytrixFuckCheats plugin) {
        super(plugin, "Criticals", "A", Category.COMBAT);
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        Player attacker = DamageUtil.meleeAttacker(event);
        if (attacker == null || attacker.getAllowFlight()) {
            return;
        }
        if (inLiquidOrWeb(attacker)) {
            return;
        }
        if (!attacker.isOnGround() && attacker.getLocation().getY() % 1.0 == 0.0) {
            flag(plugin.getDataManager().get(attacker), "noground");
        }
    }

    private static boolean inLiquidOrWeb(Player player) {
        String feet = player.getLocation().getBlock().getType().name();
        String head = player.getEyeLocation().getBlock().getType().name();
        return isBad(feet) || isBad(head);
    }

    private static boolean isBad(String material) {
        return material.contains("WATER") || material.contains("LAVA") || material.contains("WEB");
    }
}
