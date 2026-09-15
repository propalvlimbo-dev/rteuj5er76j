package ru.elytrix.efc.checks.movement;

import com.github.retrooper.packetevents.event.PacketReceiveEvent;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Timer.A: портировано из NoCheatPlus Net.FlyingFrequency (GPL-3.0).
 * Окно 5 секунд, лимит 60 пакетов в секунду. Точный таймер
 * дополнительно ловит дословный Grim Timer. Превышение гасит
 * пакет движения — читер стоит на месте.
 */
public final class TimerA extends Check {

    private final Map<UUID, Deque<Long>> flying = new ConcurrentHashMap<>();

    public TimerA(ElytrixFuckCheats plugin) {
        super(plugin, "Timer", "A", Category.MOVEMENT);
    }

    @Override
    public void onQuit(UUID uuid) {
        flying.remove(uuid);
    }

    /** Netty-поток: пакет движения. */
    public void onPacketFlying(PacketReceiveEvent event) {
        Object raw = event.getPlayer();
        if (!(raw instanceof Player)) {
            return;
        }
        UUID uuid = ((Player) raw).getUniqueId();
        long now = System.nanoTime();
        Deque<Long> deque = flying.computeIfAbsent(uuid, key -> new ArrayDeque<>());
        double pps;
        synchronized (deque) {
            deque.addLast(now);
            while (deque.size() > 1024) {
                deque.pollFirst();
            }
            long cutoff = now - 5_000_000_000L;
            while (!deque.isEmpty() && deque.peekFirst() < cutoff) {
                deque.pollFirst();
            }
            pps = deque.size() / 5.0D;
        }
        if (pps > 60.0D) {
            event.setCancelled(true);
            try {
                plugin.getPacketManager().reportViolation(uuid, id(), String.format("%.1f/s", pps));
            } catch (Throwable ignored) {
            }
        }
    }
}
