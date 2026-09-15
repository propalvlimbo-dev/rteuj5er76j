package ru.elytrix.efc.checks.combat;

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
 * AutoClicker.A: портировано из NoCheatPlus Net.AttackFrequency (GPL-3.0).
 * Корзины атак 0.5/1/2/4/8 сек, лимиты 10/15/30/60/100.
 * Превышение гасит пакет атаки.
 */
public final class AutoClickerA extends Check {

    private final Map<UUID, Deque<Long>> attacks = new ConcurrentHashMap<>();

    public AutoClickerA(ElytrixFuckCheats plugin) {
        super(plugin, "AutoClicker", "A", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        attacks.remove(uuid);
    }

    /** Netty-поток: пакет атаки. */
    public void onPacketAttack(PacketReceiveEvent event) {
        Object raw = event.getPlayer();
        if (!(raw instanceof Player)) {
            return;
        }
        UUID uuid = ((Player) raw).getUniqueId();
        long now = System.nanoTime();
        Deque<Long> deque = attacks.computeIfAbsent(uuid, key -> new ArrayDeque<>());
        String detail = null;
        synchronized (deque) {
            deque.addLast(now);
            while (deque.size() > 512) {
                deque.pollFirst();
            }
            long half = now - 500_000_000L;
            long one = now - 1_000_000_000L;
            long two = now - 2_000_000_000L;
            long four = now - 4_000_000_000L;
            long eight = now - 8_000_000_000L;
            int cHalf = 0;
            int cOne = 0;
            int cTwo = 0;
            int cFour = 0;
            int cEight = 0;
            for (long time : deque) {
                if (time < eight) {
                    continue;
                }
                cEight++;
                if (time >= four) {
                    cFour++;
                }
                if (time >= two) {
                    cTwo++;
                }
                if (time >= one) {
                    cOne++;
                }
                if (time >= half) {
                    cHalf++;
                }
            }
            while (!deque.isEmpty() && deque.peekFirst() < eight) {
                deque.pollFirst();
            }
            if (cHalf > 10) {
                detail = cHalf + "/0.5s";
            } else if (cOne > 15) {
                detail = cOne + "/1s";
            } else if (cTwo > 30) {
                detail = cTwo + "/2s";
            } else if (cFour > 60) {
                detail = cFour + "/4s";
            } else if (cEight > 100) {
                detail = cEight + "/8s";
            }
        }
        if (detail != null) {
            event.setCancelled(true);
            try {
                plugin.getPacketManager().reportViolation(uuid, id(), detail);
            } catch (Throwable ignored) {
            }
        }
    }
}
