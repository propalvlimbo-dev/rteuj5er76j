package ru.elytrix.efc.checks.movement;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Timer.B: дырявое ведро по мотивам Grim Timer.
 * Каждое движение +50 мс кредита, прошедшее время кредит гасит.
 * Пачки движений (батчинг сети, догоняющие тики) ведром поглощаются,
 * sustained-избыток — только у таймер-чита.
 * Портировано из Grim (GPL-3.0), адаптировано под главный поток.
 */
public final class TimerB extends Check {

    private final Map<UUID, Long> balance = new ConcurrentHashMap<>();
    private final Map<UUID, Long> lastMove = new ConcurrentHashMap<>();

    public TimerB(ElytrixFuckCheats plugin) {
        super(plugin, "Timer", "B", Category.MOVEMENT);
    }

    @Override
    public void onQuit(UUID uuid) {
        balance.remove(uuid);
        lastMove.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        if (player == null) {
            return;
        }
        UUID id = player.getUniqueId();
        long now = System.currentTimeMillis();
        long prev = lastMove.getOrDefault(id, now);
        lastMove.put(id, now);
        long elapsed = now - prev;
        if (elapsed < 0) {
            elapsed = 0;
        }
        if (elapsed > 5000) {
            elapsed = 5000;
        }
        long bal = balance.getOrDefault(id, 0L);
        bal += 50;
        bal -= elapsed;
        if (bal < -1000) {
            bal = -1000;
        }
        if (bal > 350) {
            bal = 350;
        }
        if (bal > 300) {
            balance.put(id, 250L);
            flag(plugin.getDataManager().get(player), "timer");
            return;
        }
        balance.put(id, bal);
    }
}
