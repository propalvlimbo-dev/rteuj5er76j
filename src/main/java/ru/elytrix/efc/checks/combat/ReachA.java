package ru.elytrix.efc.checks.combat;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.GameMode;
import org.bukkit.Location;
import org.bukkit.entity.EnderDragon;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Giant;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Reach.A: портировано из NoCheatPlus Fight.Reach (GPL-3.0).
 * Классический check(): лимит 4.4 (выживание) / 6.0 (креатив),
 * дракон +6.5, гигант +1.5, динамическое сужение reachMod
 * (дальность 0.9, шаг 0.15), тихая отмена в полосе сужения,
 * награда x0.8. Нарушение гасит урон.
 */
public final class ReachA extends Check {

    private static final double SURVIVAL_DISTANCE = 4.4D;
    private static final double CREATIVE_DISTANCE = 6.0D;
    private static final double DYNAMIC_RANGE = 0.9D;
    private static final double DYNAMIC_STEP = 0.15D / SURVIVAL_DISTANCE;

    private final Map<UUID, Double> reachVL = new ConcurrentHashMap<>();
    private final Map<UUID, Double> reachMod = new ConcurrentHashMap<>();

    public ReachA(ElytrixFuckCheats plugin) {
        super(plugin, "Reach", "A", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        reachVL.remove(uuid);
        reachMod.remove(uuid);
    }

    private static double getDistMod(Entity damaged) {
        if (damaged instanceof EnderDragon) {
            return 6.5D;
        } else if (damaged instanceof Giant) {
            return 1.5D;
        }
        return 0.0D;
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        if (!(event.getDamager() instanceof Player)) {
            return;
        }
        Player player = (Player) event.getDamager();
        Entity damaged = event.getEntity();
        UUID uuid = player.getUniqueId();

        double distanceLimit = player.getGameMode() == GameMode.CREATIVE
                ? CREATIVE_DISTANCE : SURVIVAL_DISTANCE + getDistMod(damaged);
        double distanceMin = (distanceLimit - DYNAMIC_RANGE) / distanceLimit;

        double height = damaged instanceof Player ? 1.8D : 2.0D;

        Location pLoc = player.getLocation();
        Location dLoc = damaged.getLocation();
        double pY = pLoc.getY() + 1.62D;
        double dY = dLoc.getY();
        double refY;
        if (pY <= dY) {
            refY = dY;
        } else if (pY >= dY + height) {
            refY = dY + height;
        } else {
            refY = pY;
        }

        double dx = dLoc.getX() - pLoc.getX();
        double dy = refY - pY;
        double dz = dLoc.getZ() - pLoc.getZ();
        double lenpRel = Math.sqrt(dx * dx + dy * dy + dz * dz);
        double violation = lenpRel - distanceLimit;
        double mod = reachMod.getOrDefault(uuid, 1.0D);

        boolean cancel = false;
        if (violation > 0) {
            reachVL.put(uuid, reachVL.getOrDefault(uuid, 0.0D) + violation);
            flag(plugin.getDataManager().get(player),
                    String.format("%.2f/%.2f", lenpRel, distanceLimit));
            cancel = true;
        } else if (lenpRel - distanceLimit * mod > 0) {
            cancel = true;
        } else {
            reachVL.put(uuid, reachVL.getOrDefault(uuid, 0.0D) * 0.8D);
        }

        if (lenpRel > distanceLimit - DYNAMIC_RANGE) {
            reachMod.put(uuid, Math.max(distanceMin, mod - DYNAMIC_STEP));
        } else {
            reachMod.put(uuid, Math.min(1.0D, mod + DYNAMIC_STEP));
        }

        if (cancel) {
            event.setCancelled(true);
        }
    }
}
