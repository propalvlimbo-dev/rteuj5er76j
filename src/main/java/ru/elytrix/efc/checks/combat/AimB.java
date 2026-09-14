package ru.elytrix.efc.checks.combat;

import java.util.ArrayDeque;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Aim.B: линейное наведение — 20 пакетов подряд с почти одинаковым шагом.
 * Живая рука так ровно не ведёт, только робот. Только в бою.
 */
public final class AimB extends Check {

    private final Map<UUID, ArrayDeque<Double>> deltas = new ConcurrentHashMap<>();

    public AimB(ElytrixFuckCheats plugin) {
        super(plugin, "Aim", "B", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        deltas.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        double delta = yawDelta(event.getFrom().getYaw(), event.getTo().getYaw());
        if (delta < 0.1 || delta > 20) {
            return;
        }
        ArrayDeque<Double> window = deltas.computeIfAbsent(player.getUniqueId(), key -> new ArrayDeque<>());
        window.addLast(delta);
        while (window.size() > 20) {
            window.pollFirst();
        }
        if (window.size() < 20) {
            return;
        }
        long now = System.currentTimeMillis();
        if (now - plugin.getDataManager().get(player).getLastAttack() > 3000) {
            return;
        }
        double min = Double.MAX_VALUE;
        double max = 0;
        for (double value : window) {
            if (value < min) {
                min = value;
            }
            if (value > max) {
                max = value;
            }
        }
        if (min > 0 && max / min < 1.05) {
            window.clear();
            flag(plugin.getDataManager().get(player), "linear");
        }
    }

    private static double yawDelta(double from, double to) {
        double delta = Math.abs(from - to) % 360.0;
        return delta > 180.0 ? 360.0 - delta : delta;
    }
}
