package ru.elytrix.efc.checks.combat;

import org.bukkit.GameMode;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.potion.PotionEffectType;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Criticals.A: ядро из NoCheatPlus Fight.Critical (GPL-3.0).
 * Легитный крит требует реального падения. Дистанция падения
 * в (0, 0.06251) вне воды/транспорта/полёта/слепоты —
 * поддельный крит. Нарушение гасит урон.
 */
public final class CriticalsA extends Check {

    private static final double FALL_DISTANCE = 0.06251D;

    public CriticalsA(ElytrixFuckCheats plugin) {
        super(plugin, "Criticals", "A", Category.COMBAT);
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        if (!(event.getDamager() instanceof Player)) {
            return;
        }
        Player player = (Player) event.getDamager();
        if (player.getGameMode() == GameMode.CREATIVE || player.getAllowFlight()) {
            return;
        }
        double fallDistance = player.getFallDistance();
        if (fallDistance > 0.0D && !player.isInsideVehicle()
                && !player.hasPotionEffect(PotionEffectType.BLINDNESS)
                && !player.isInWater() && !player.isGliding()
                && fallDistance < FALL_DISTANCE) {
            event.setCancelled(true);
            flag(plugin.getDataManager().get(player), "fd=" + fallDistance);
        }
    }
}
