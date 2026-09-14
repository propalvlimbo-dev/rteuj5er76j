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
 * AutoClicker.B: наглый CPS выше 30 — так не кликает никто из людей.
 */
public final class AutoClickerB extends Check {

    private final Map<UUID, ArrayDeque<Long>> clicks = new ConcurrentHashMap<>();

    public AutoClickerB(ElytrixFuckCheats plugin) {
        super(plugin, "AutoClicker", "B", Category.COMBAT);
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
        if (times.size() > cfg("blatant-cps", 30.0)) {
            flag(plugin.getDataManager().get(player), times.size() + "cps");
        }
    }
}
