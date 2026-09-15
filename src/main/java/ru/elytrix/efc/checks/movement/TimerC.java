package ru.elytrix.efc.checks.movement;

import java.util.ArrayDeque;
import java.util.Deque;
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
 * Timer.C: движений сильно меньше тикрейта при активном движении
 * (по мотивам Grim NegativeTimer). Окно 2 с: прошёл 4+ блока меньше
 * чем за 15 движений — чит. Пачки сети на счёт не влияют.
 * Портировано из Grim (GPL-3.0), адаптировано под главный поток.
 */
public final class TimerC extends Check {

    private final Map<UUID, Deque<double[]>> windows = new ConcurrentHashMap<>();

    public TimerC(ElytrixFuckCheats plugin) {
        super(plugin, "Timer", "C", Category.MOVEMENT);
    }

    @Override
    public void onQuit(UUID uuid) {
        windows.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        if (player == null || event.getFrom() == null || event.getTo() == null) {
            return;
        }
        UUID id = player.getUniqueId();
        long now = System.currentTimeMillis();
        Deque<double[]> window = windows.computeIfAbsent(id, key -> new ArrayDeque<>());
        window.addLast(new double[]{now, event.getTo().getX(), event.getTo().getZ()});
        while (!window.isEmpty() && now - window.peekFirst()[0] > 2000) {
            window.pollFirst();
        }
        if (window.size() < 10) {
            return;
        }
        double dist = 0;
        double[] prev = null;
        for (double[] point : window) {
            if (prev != null) {
                double dx = point[1] - prev[1];
                double dz = point[2] - prev[2];
                dist += Math.sqrt(dx * dx + dz * dz);
            }
            prev = point;
        }
        if (dist < 4.0) {
            return;
        }
        if (window.size() < 15) {
            int count = window.size();
            window.clear();
            flag(plugin.getDataManager().get(player),
                    "slow " + count + " moves/" + String.format("%.1f", dist) + "m");
        }
    }
}
