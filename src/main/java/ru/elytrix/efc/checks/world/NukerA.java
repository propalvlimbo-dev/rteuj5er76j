package ru.elytrix.efc.checks.world;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.block.BlockBreakEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.BlockUtil;

/**
 * Nuker.A: 4+ сломанных блока за 120 мс.
 * Легитный потолок — 1 блок в тик (инста-копка 20/с = 2 блока за 120 мс
 * на стыке окна), так что 4 за 120 мс невозможно даже с догоняющими тиками.
 */
public final class NukerA extends Check {

    private final Map<UUID, Deque<Long>> breaks = new ConcurrentHashMap<>();

    public NukerA(ElytrixFuckCheats plugin) {
        super(plugin, "Nuker", "A", Category.WORLD);
    }

    @Override
    public void onQuit(UUID uuid) {
        breaks.remove(uuid);
        BlockUtil.clear(uuid);
    }

    @EventHandler
    public void onBreak(BlockBreakEvent event) {
        Player player = event.getPlayer();
        if (player == null || event.getBlock() == null) {
            return;
        }
        UUID id = player.getUniqueId();
        BlockUtil.noteBreak(id);
        long now = System.currentTimeMillis();
        Deque<Long> times = breaks.computeIfAbsent(id, key -> new ArrayDeque<>());
        times.addLast(now);
        while (!times.isEmpty() && now - times.peekFirst() > 120) {
            times.pollFirst();
        }
        if (times.size() >= 4) {
            long span = now - times.peekFirst();
            times.clear();
            event.setCancelled(true);
            flag(plugin.getDataManager().get(player), "4 breaks in " + span + "ms");
        }
    }
}
