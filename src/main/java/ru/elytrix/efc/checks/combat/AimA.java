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
 * Aim.A: GCD-анализ — повороты мыши лежат на «сетке» чувствительности,
 * а аимботы ставят голову на произвольные углы.
 * Работает только в бою (удар в последние 3 сек), окно 60 поворотов.
 * Легит: ~100% на сетке. Чит: единицы процентов.
 */
public final class AimA extends Check {

    private final Map<UUID, ArrayDeque<Double>> deltas = new ConcurrentHashMap<>();

    public AimA(ElytrixFuckCheats plugin) {
        super(plugin, "Aim", "A", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        deltas.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        double delta = yawDelta(event.getFrom().getYaw(), event.getTo().getYaw());
        if (delta < 0.01 || delta > 30) {
            return;
        }
        ArrayDeque<Double> window = deltas.computeIfAbsent(player.getUniqueId(), key -> new ArrayDeque<>());
        window.addLast(delta);
        while (window.size() > 60) {
            window.pollFirst();
        }
        if (window.size() < 60) {
            return;
        }
        long now = System.currentTimeMillis();
        if (now - plugin.getDataManager().get(player).getLastAttack() > 3000) {
            return;
        }
        long[] scaled = new long[window.size()];
        int i = 0;
        for (double value : window) {
            scaled[i++] = Math.round(value * 100000);
        }
        window.clear();
        long grid = scaled[0];
        for (long value : scaled) {
            if (value != 0) {
                grid = gcd(grid, value);
            }
        }
        if (grid < 10) {
            return;
        }
        long tolerance = Math.max(2, (long) (grid * 0.01));
        int matches = 0;
        for (long value : scaled) {
            long rest = Math.abs(value % grid);
            long distanceToGrid = Math.min(rest, grid - rest);
            if (distanceToGrid <= tolerance) {
                matches++;
            }
        }
        double ratio = (double) matches / scaled.length;
        if (ratio < 0.30) {
            flag(plugin.getDataManager().get(player), "off-grid " + Math.round(ratio * 100) + "%");
        }
    }

    private static double yawDelta(double from, double to) {
        double delta = Math.abs(from - to) % 360.0;
        return delta > 180.0 ? 360.0 - delta : delta;
    }

    private static long gcd(long a, long b) {
        a = Math.abs(a);
        b = Math.abs(b);
        while (b != 0) {
            long next = a % b;
            a = b;
            b = next;
        }
        return a;
    }
}
