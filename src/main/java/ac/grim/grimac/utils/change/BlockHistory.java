package ac.grim.grimac.utils.change;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.function.Predicate;

/**
 * EFC-совместимость: Grim BlockHistory.
 */
public class BlockHistory {

    private final Deque<BlockModification> recent = new ArrayDeque<>();

    public synchronized void add(BlockModification modification) {
        recent.addLast(modification);
        while (recent.size() > 64) {
            recent.pollFirst();
        }
    }

    public synchronized Iterable<BlockModification> getRecentModifications(Predicate<BlockModification> filter) {
        List<BlockModification> out = new ArrayList<>();
        for (BlockModification mod : recent) {
            try {
                if (filter.test(mod)) out.add(mod);
            } catch (Throwable ignored) {
            }
        }
        return out;
    }
}
