package ru.elytrix.efc.checks.world;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.block.BlockPlaceEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Scaffold.A: 4+ установок за 120 мс.
 * Живой игрок жмёт ~8-15 раз в секунду (2 блока за 120 мс на стыке окна),
 * 4 за 120 мс = 33/с — невозможно руками.
 */
public final class ScaffoldA extends Check {

    private final Map<UUID, Deque<Long>> places = new ConcurrentHashMap<>();

    public ScaffoldA(ElytrixFuckCheats plugin) {
        super(plugin, "Scaffold", "A", Category.WORLD);
    }

    @Override
    public void onQuit(UUID uuid) {
        places.remove(uuid);
    }

    @EventHandler
    public void onPlace(BlockPlaceEvent event) {
        Player player = event.getPlayer();
        if (player == null || event.getBlock() == null) {
            return;
        }
        UUID id = player.getUniqueId();
        long now = System.currentTimeMillis();
        Deque<Long> times = places.computeIfAbsent(id, key -> new ArrayDeque<>());
        times.addLast(now);
        while (!times.isEmpty() && now - times.peekFirst() > 120) {
            times.pollFirst();
        }
        if (times.size() >= 4) {
            long span = now - times.peekFirst();
            times.clear();
            flag(plugin.getDataManager().get(player), "4 places in " + span + "ms");
        }
    }
}
