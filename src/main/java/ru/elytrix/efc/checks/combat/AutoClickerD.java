package ru.elytrix.efc.checks.combat;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.DamageUtil;

/**
 * AutoClicker.D: темп ударов (порт Hawk FightSpeed).
 * Средний CPS за 10 ударов выше 16 — автокликер. В отличие от проверок
 * по взмахам работает и на новых клиентах: удары долетают всегда.
 * Мульти-урон в один тик (свип) пропускаем, пауза &gt;200 мс сбрасывает серию.
 */
public final class AutoClickerD extends Check {

    private static final class State {
        final Deque<Long> intervals = new ArrayDeque<>();
        long lastHit;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public AutoClickerD(ElytrixFuckCheats plugin) {
        super(plugin, "AutoClicker", "D", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        Player attacker = DamageUtil.meleeAttacker(event);
        if (attacker == null) {
            return;
        }
        State state = states.computeIfAbsent(attacker.getUniqueId(), key -> new State());
        long now = System.currentTimeMillis();
        if (state.lastHit > 0) {
            long dt = now - state.lastHit;
            if (dt > 200) {
                state.intervals.clear();
            } else if (dt >= 10) {
                state.intervals.addLast(dt);
                while (state.intervals.size() > 10) {
                    state.intervals.removeFirst();
                }
                if (state.intervals.size() >= 10) {
                    double sum = 0;
                    for (long interval : state.intervals) {
                        sum += interval;
                    }
                    double cps = 1000 / (sum / state.intervals.size());
                    if (cps > cfg("max-cps", 16)) {
                        flag(plugin.getDataManager().get(attacker),
                                "cps " + String.format("%.1f", cps));
                    }
                }
            }
        }
        state.lastHit = now;
    }
}
