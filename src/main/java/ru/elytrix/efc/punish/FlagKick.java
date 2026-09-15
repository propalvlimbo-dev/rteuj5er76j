package ru.elytrix.efc.punish;

import java.util.ArrayDeque;
import java.util.Arrays;
import java.util.Collections;
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
 * Быстрый кик от флагов. Три полосы:
 * 1) связка: 3+ РАЗНЫХ проверки боя за 90 сек — кик;
 * 2) приговор: 2 флага проверки-приговора за 90 сек — кик;
 * 3) повтор: 4 флага ОДНОЙ точной проверки за 90 сек — кик.
 * Один и тот же флаг дважды может дёрнуться на лагере, два разных —
 * уже нет; повтор разрешён только точным проверкам (рич и прочие
 * лагозависимые идут своими порогами). Одиночки тают как раньше.
 * Очередь чистится только реальным киком: кулдаун пережидаем
 * и добиваем следующим флагом.
 */
public final class FlagKick {

    private static final long WINDOW_MS = 90000;

    /** Проверки-приговоры: два флага за 90 сек — читер почти наверняка. */
    private static final Set<String> TWO = Collections.unmodifiableSet(new HashSet<>(Arrays.asList(
            "KillAura.A", "KillAura.D", "KillAura.F", "KillAura.G",
            "Aim.F", "Aim.G", "AutoClicker.A")));

    /** Проверки, чей повтор 4 раза за 90 сек — уже приговор. */
    private static final Set<String> REPEAT = Collections.unmodifiableSet(new HashSet<>(Arrays.asList(
            "KillAura.A", "KillAura.B", "KillAura.D", "KillAura.F", "KillAura.G",
            "Aim.C", "Aim.F", "Accuracy.A", "Accuracy.B", "Accuracy.C",
            "AutoClicker.A", "AutoClicker.B")));

    private static final class Entry {
        long time;
        String check;
    }

    private final ElytrixFuckCheats plugin;
    private final Map<UUID, Deque<Entry>> flags = new ConcurrentHashMap<>();

    public FlagKick(ElytrixFuckCheats plugin) {
        this.plugin = plugin;
    }

    /** Accuracy A/B/C — один сигнал точности на разных окнах, а не три разных. */
    private static String family(String id) {
        return id.startsWith("Accuracy.") ? "Accuracy" : id;
    }

    public void onFlag(Player player, Check check) {
        if (check.getCategory() != Category.COMBAT) {
            return;
        }
        if ("HitBox.A".equals(check.id())) {
            // Хитбокс: только блок удара + алерты, в кик-логике не участвует.
            return;
        }
        long now = System.currentTimeMillis();
        UUID uuid = player.getUniqueId();
        Deque<Entry> queue = flags.computeIfAbsent(uuid, key -> new ArrayDeque<>());
        boolean fire;
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
            Set<String> distinct = new HashSet<>();
            int same = 0;
            for (Entry old : queue) {
                distinct.add(family(old.check));
                if (old.check.equals(check.id())) {
                    same++;
                }
            }
            fire = distinct.size() >= 3
                    || (TWO.contains(check.id()) && same >= 2)
                    || (REPEAT.contains(check.id()) && same >= 4);
        }
        if (fire) {
            boolean punished = plugin.getPunishmentManager().onFlag(
                    plugin.getDataManager().get(player), check, check.getMaxVl());
            if (punished) {
                synchronized (queue) {
                    queue.clear();
                }
            }
        }
    }
}
