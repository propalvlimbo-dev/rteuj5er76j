package ru.elytrix.efc.checks.combat;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.block.Action;
import org.bukkit.event.player.PlayerInteractEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * AutoClicker.C: жёсткий лимит кликов (порт NESS MaxCPS).
 * NESS считает клики в воздухе за секунду, дефолт 18 — так и делаем,
 * только окно скользящее (честнее: не зависит от границы секунды).
 */
public final class AutoClickerC extends Check {

    private final Map<UUID, Deque<Long>> clicks = new ConcurrentHashMap<>();

    public AutoClickerC(ElytrixFuckCheats plugin) {
        super(plugin, "AutoClicker", "C", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        clicks.remove(uuid);
    }

    @EventHandler
    public void onInteract(PlayerInteractEvent event) {
        Action action = event.getAction();
        if (action != Action.LEFT_CLICK_AIR && action != Action.RIGHT_CLICK_AIR) {
            return;
        }
        Player player = event.getPlayer();
        long now = System.currentTimeMillis();
        Deque<Long> deque = clicks.computeIfAbsent(player.getUniqueId(), key -> new ArrayDeque<>());
        deque.addLast(now);
        while (!deque.isEmpty() && now - deque.getFirst() > 1000) {
            deque.removeFirst();
        }
        if (deque.size() > cfg("max-cps", 18)) {
            flag(plugin.getDataManager().get(player), "cps " + deque.size());
        }
    }
}
