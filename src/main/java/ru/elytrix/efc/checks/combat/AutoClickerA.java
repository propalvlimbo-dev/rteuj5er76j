package ru.elytrix.efc.checks.combat;

import java.util.ArrayDeque;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerAnimationEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * AutoClicker.A: нечеловеческий CPS с машинной стабильностью.
 * Флагает только связку «>20 кликов в секунду + почти нулевой разброс пауз».
 * Драг-кликеры (быстро, но неровно) и баттерфляй (ровно, но медленно) проходят.
 */
public final class AutoClickerA extends Check {

    private final Map<UUID, ArrayDeque<Long>> clicks = new ConcurrentHashMap<>();

    public AutoClickerA(ElytrixFuckCheats plugin) {
        super(plugin, "AutoClicker", "A", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        clicks.remove(uuid);
    }

    @EventHandler
    public void onAnimation(PlayerAnimationEvent event) {
        Player player = event.getPlayer();
        ArrayDeque<Long> times = clicks.computeIfAbsent(player.getUniqueId(), key -> new ArrayDeque<>());
        long now = System.currentTimeMillis();
        times.addLast(now);
        while (!times.isEmpty() && now - times.peekFirst() > 1000) {
            times.pollFirst();
        }
        int cps = times.size();
        if (cps < cfg("max-cps", 20.0) || cps < 15) {
            return;
        }
        // Разброс пауз между кликами: у бота почти ноль, у человека десятки мс.
        Long previous = null;
        double sum = 0;
        double sumSquares = 0;
        int intervals = 0;
        for (Long time : times) {
            if (previous != null) {
                double gap = (double) (time - previous);
                sum += gap;
                sumSquares += gap * gap;
                intervals++;
            }
            previous = time;
        }
        if (intervals < 10) {
            return;
        }
        double mean = sum / intervals;
        double stddev = Math.sqrt(Math.max(0, sumSquares / intervals - mean * mean));
        if (stddev <= cfg("max-stddev-ms", 10.0)) {
            flag(plugin.getDataManager().get(player), cps + "cps const");
        }
    }
}
