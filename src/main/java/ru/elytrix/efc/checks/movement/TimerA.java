package ru.elytrix.efc.checks.movement;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Timer.A: больше 20 движений в секунду (спидер пакетов).
 * Легитный клиент шлёт максимум 1 движение в тик = 20/с; планка 60/2с
 * ловит таймер от x1.5. Лаги сервера дают меньше событий, не больше.
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

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
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
