package ru.elytrix.efc.punish;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Быстрый кик от связки флагов: 6+ флагов боя от 2+ разных проверок
 * за 90 секунд — это уже не везение, а читер. Одиночные проверки со
 * своими порогами не тронуты; связка — добивающий удар по тем, кто
 * размазывает слабые сигналы (джиттер-лок без ритма и снапов).
 * Кикает командой триггерной проверки (её секретный код).
 * Пустые очереди вычищаются сами; остаток после выхода ничтожен.
 */
public final class FlagKick {

    private static final int COUNT = 6;
    private static final int DISTINCT = 2;
    private static final long WINDOW_MS = 90000;

    private static final class Entry {
        long time;
        String check;
    }

    private final ElytrixFuckCheats plugin;
    private final Map<UUID, Deque<Entry>> flags = new ConcurrentHashMap<>();

    public FlagKick(ElytrixFuckCheats plugin) {
        this.plugin = plugin;
    }

    public void onFlag(Player player, Check check) {
        if (check.getCategory() != Category.COMBAT) {
            return;
        }
        long now = System.currentTimeMillis();
        UUID uuid = player.getUniqueId();
        Deque<Entry> queue = flags.computeIfAbsent(uuid, key -> new ArrayDeque<>());
        synchronized (queue) {
            Entry entry = new Entry();
            entry.time = now;
            entry.check = check.id();
            queue.addLast(entry);
            while (!queue.isEmpty() && now - queue.peekFirst().time > WINDOW_MS) {
                queue.removeFirst();
            }
            if (queue.isEmpty()) {
                flags.remove(uuid);
                return;
            }
            if (queue.size() < COUNT) {
                return;
            }
            Set<String> distinct = new HashSet<>();
            for (Entry old : queue) {
                distinct.add(old.check);
            }
            if (distinct.size() < DISTINCT) {
                return;
            }
            queue.clear();
        }
        plugin.getPunishmentManager().onFlag(
                plugin.getDataManager().get(player), check, check.getMaxVl());
    }
}
