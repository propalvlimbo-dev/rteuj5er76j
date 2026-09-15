package ru.elytrix.efc.checks.movement;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.data.PlayerData;

/**
 * Timer.A: больше 20 движений в секунду (спидер пакетов).
 * С пакетным слоем считает точные Flying (флаг при &gt;25/с),
 * без него — события движения (флаг при &gt;60/2с). Лаги сервера
 * дают меньше событий, не больше, — ложным взяться неоткуда.
 */
public final class TimerA extends Check {

    private static final class State {
        final Deque<Long> ticks = new ArrayDeque<>();
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public TimerA(ElytrixFuckCheats plugin) {
        super(plugin, "Timer", "A", Category.MOVEMENT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    /** Флаг из пакетного слоя (точный счёт Flying). */
    public void packetFlag(UUID uuid, String details) {
        PlayerData data = plugin.getDataManager().get(uuid);
        Player player = data.getPlayer();
        if (player == null || !player.isOnline()) {
            return;
        }
        flag(data, details);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        if (plugin.getPacketManager().isAvailable()) {
            return;
        }
        State state = states.computeIfAbsent(
                event.getPlayer().getUniqueId(), key -> new State());
        long now = System.currentTimeMillis();
        state.ticks.addLast(now);
        while (!state.ticks.isEmpty() && now - state.ticks.peekFirst() > 2000) {
            state.ticks.removeFirst();
        }
        if (state.ticks.size() > 60) {
            int count = state.ticks.size();
            state.ticks.clear();
            flag(plugin.getDataManager().get(event.getPlayer()), count + "/2s");
        }
    }
}
