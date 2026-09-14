package ru.elytrix.efc.data;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.Location;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import ru.elytrix.efc.ElytrixFuckCheats;

/**
 * Мини лаг-компенсация как у топов (Hawk LagCompensator, Grim rewind).
 * Храним позиции каждого игрока за ~3 сек: на момент удара смотрим,
 * где жертва БЫЛА глазами атакующего, а не где она уже есть.
 */
public final class PositionHistory implements Listener {

    private static final class Sample {
        final long time;
        final double x;
        final double y;
        final double z;
        final float yaw;
        final float pitch;

        Sample(long time, double x, double y, double z, float yaw, float pitch) {
            this.time = time;
            this.x = x;
            this.y = y;
            this.z = z;
            this.yaw = yaw;
            this.pitch = pitch;
        }
    }

    private final Map<UUID, Deque<Sample>> histories = new ConcurrentHashMap<>();

    public PositionHistory(ElytrixFuckCheats plugin) {
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Deque<Sample> deque = histories.computeIfAbsent(event.getPlayer().getUniqueId(),
                key -> new ArrayDeque<>());
        Location to = event.getTo();
        deque.addLast(new Sample(System.currentTimeMillis(),
                to.getX(), to.getY(), to.getZ(), to.getYaw(), to.getPitch()));
        while (deque.size() > 60) {
            deque.removeFirst();
        }
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        histories.remove(event.getPlayer().getUniqueId());
    }

    /** Позиция игрока на момент времени (ближайший семпл не новее). */
    public Location locationAt(Player player, long timestamp) {
        Location current = player.getLocation();
        Deque<Sample> deque = histories.get(player.getUniqueId());
        if (deque == null || deque.isEmpty()) {
            return current;
        }
        Sample best = null;
        for (Sample sample : deque) {
            if (sample.time > timestamp) {
                break;
            }
            best = sample;
        }
        if (best == null) {
            best = deque.getFirst();
        }
        return new Location(current.getWorld(), best.x, best.y, best.z, best.yaw, best.pitch);
    }
}
