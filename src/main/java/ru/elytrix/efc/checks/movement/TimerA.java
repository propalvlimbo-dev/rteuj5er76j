package ru.elytrix.efc.checks.movement;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.event.player.PlayerTeleportEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Timer.A: счёт движений по серверным тикам (только Bukkit, без пакетов).
 * Легит: <=1 движение в тик. Лаг-пачки режутся вкладом max 2 на тик —
 * их даёт один тик, а таймер-чит даёт 2 движения КАЖДЫЙ тик секунду подряд.
 * Окно 20 тиков, флаг при сумме > 28.
 */
public final class TimerA extends Check {

    private final Map<UUID, AtomicInteger> tickCount = new ConcurrentHashMap<>();
    private final Map<UUID, Deque<Integer>> window = new ConcurrentHashMap<>();

    public TimerA(ElytrixFuckCheats plugin) {
        super(plugin, "Timer", "A", Category.MOVEMENT);
        plugin.getServer().getScheduler().runTaskTimer(plugin, this::tick, 1L, 1L);
    }

    @Override
    public void onQuit(UUID uuid) {
        tickCount.remove(uuid);
        window.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        if (player == null) {
            return;
        }
        tickCount.computeIfAbsent(player.getUniqueId(), key -> new AtomicInteger()).incrementAndGet();
    }

    @EventHandler
    public void onTeleport(PlayerTeleportEvent event) {
        Player player = event.getPlayer();
        if (player != null) {
            tickCount.remove(player.getUniqueId());
            window.remove(player.getUniqueId());
        }
    }

    private void tick() {
        for (Map.Entry<UUID, AtomicInteger> entry : tickCount.entrySet()) {
            UUID uuid = entry.getKey();
            int count = Math.min(2, Math.max(0, entry.getValue().getAndSet(0)));
            Deque<Integer> deque = window.computeIfAbsent(uuid, key -> new ArrayDeque<>());
            deque.addLast(count);
            while (deque.size() > 20) {
                deque.pollFirst();
            }
            if (deque.size() < 20) {
                continue;
            }
            int sum = 0;
            for (int value : deque) {
                sum += value;
            }
            if (sum > 28) {
                deque.clear();
                flag(plugin.getDataManager().get(uuid), sum + "/20t");
            }
        }
    }
}
