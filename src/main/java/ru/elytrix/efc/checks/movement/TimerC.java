package ru.elytrix.efc.checks.movement;

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
 * Timer.C: движения реже тикрейта (Grim NegativeTimer).
 * Долг растёт за гэпы дольше 150 мс во время реального движения,
 * тает на ровных тиках. Гэп дольше 5 с — простой/лаг, долг сгорает.
 * Портировано из Grim (GPL-3.0), адаптировано под главный поток.
 */
public final class TimerC extends Check {

    private final Map<UUID, Long> lastMove = new ConcurrentHashMap<>();
    private final Map<UUID, Long> debt = new ConcurrentHashMap<>();

    public TimerC(ElytrixFuckCheats plugin) {
        super(plugin, "Timer", "C", Category.MOVEMENT);
    }

    @Override
    public void onQuit(UUID uuid) {
        lastMove.remove(uuid);
        debt.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        if (player == null || event.getFrom() == null || event.getTo() == null) {
            return;
        }
        double dx = event.getTo().getX() - event.getFrom().getX();
        double dz = event.getTo().getZ() - event.getFrom().getZ();
        if (Math.sqrt(dx * dx + dz * dz) < 0.05) {
            return;
        }
        UUID id = player.getUniqueId();
        long now = System.currentTimeMillis();
        long prev = lastMove.getOrDefault(id, now);
        lastMove.put(id, now);
        long gap = now - prev;
        if (gap < 0) {
            gap = 0;
        }
        if (gap > 5000) {
            debt.remove(id);
            return;
        }
        long owed = debt.getOrDefault(id, 0L);
        if (gap > 150) {
            owed += gap - 150;
        } else {
            owed = Math.max(0, owed - 50);
        }
        if (owed > 1200) {
            debt.put(id, 600L);
            flag(plugin.getDataManager().get(player), "negative gap=" + gap + "ms");
            return;
        }
        debt.put(id, owed);
    }
}
