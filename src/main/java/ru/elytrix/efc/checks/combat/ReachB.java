package ru.elytrix.efc.checks.combat;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.CombatGeometry;
import ru.elytrix.efc.util.DamageUtil;

/**
 * Reach.B: средняя дистанция за 25 ударов (та же метрика Hawk — глаз-&gt;бокс).
 * Ловит «умный» рич 3.3–3.5, который прячется от разовых замеров.
 * Только игроки, лимит с компенсацией пинга.
 */
public final class ReachB extends Check {

    private static final class State {
        int count;
        double sum;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public ReachB(ElytrixFuckCheats plugin) {
        super(plugin, "Reach", "B", Category.COMBAT);
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
        Entity rawVictim = DamageUtil.entityOf(event);
        if (!(rawVictim instanceof Player)) {
            return;
        }
        Player victim = (Player) rawVictim;
        State state = states.computeIfAbsent(attacker.getUniqueId(), key -> new State());
        state.sum += CombatGeometry.eyeToBoxDistance(attacker, victim, 0.1);
        state.count++;
        if (state.count < 25) {
            return;
        }
        double average = state.sum / state.count;
        state.count = 0;
        state.sum = 0;
        double max = DamageUtil.reachLimit(attacker, victim,
                cfg("base", 3.0), cfg("per-ms", 0.0025), cfg("cap", 4.0));
        if (average > max) {
            flag(plugin.getDataManager().get(attacker), "avg " + String.format("%.2f", average));
        }
    }
}
