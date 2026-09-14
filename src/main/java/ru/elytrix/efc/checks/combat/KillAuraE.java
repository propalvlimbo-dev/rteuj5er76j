package ru.elytrix.efc.checks.combat;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Entity;
import org.bukkit.entity.LivingEntity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.util.Vector;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.data.PlayerData;
import ru.elytrix.efc.util.DamageUtil;

/**
 * KillAura.E: паттерн угла (порт NESS KillauraAnglePattern).
 * Угол «взгляд-&gt;жертва» на каждом ударе; раз в 4 сек считаем разброс:
 * у ауры он неестественно стабильный (&lt;17% от среднего), рука так не может.
 * Гейт NESS: атакующий должен крутиться (размах yaw &gt; 10), иначе это просто
 * добивание стоящего — там угол всегда 0.
 */
public final class KillAuraE extends Check {

    private static final class State {
        final Deque<Long> angles = new ArrayDeque<>();
        PlayerData data;
        float yawMin;
        float yawMax;
        float lastYaw;
        boolean spanInit;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public KillAuraE(ElytrixFuckCheats plugin) {
        super(plugin, "KillAura", "E", Category.COMBAT);
        plugin.getServer().getScheduler().runTaskTimer(plugin, this::evaluate, 80L, 80L);
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
        if (!(rawVictim instanceof LivingEntity)) {
            return;
        }
        State state = states.computeIfAbsent(attacker.getUniqueId(), key -> new State());
        state.data = plugin.getDataManager().get(attacker);
        Vector look = attacker.getEyeLocation().getDirection();
        Vector toVictim = rawVictim.getLocation().toVector()
                .subtract(attacker.getEyeLocation().toVector());
        state.angles.addLast((long) (look.angle(toVictim) * 10000));
        while (state.angles.size() > 10) {
            state.angles.removeFirst();
        }
        float yaw = attacker.getLocation().getYaw();
        if (!state.spanInit) {
            state.spanInit = true;
            state.yawMin = yaw;
            state.yawMax = yaw;
        } else if (Math.abs(yaw - state.lastYaw) > 100) {
            state.yawMin = yaw;
            state.yawMax = yaw;
        } else {
            state.yawMin = Math.min(state.yawMin, yaw);
            state.yawMax = Math.max(state.yawMax, yaw);
        }
        state.lastYaw = yaw;
    }

    private void evaluate() {
        for (State state : states.values()) {
            if (state.angles.size() > 1 && state.data != null) {
                double mean = 0;
                for (long angle : state.angles) {
                    mean += angle;
                }
                mean /= state.angles.size();
                double variance = 0;
                for (long angle : state.angles) {
                    double diff = angle - mean;
                    variance += diff * diff;
                }
                variance /= state.angles.size();
                double average = mean / 10000;
                double sample = (Math.sqrt(variance) / 10000) / average * 100;
                if (sample < cfg("max-precision", 17) && state.yawMax - state.yawMin > 10) {
                    flag(state.data, "pattern");
                }
            }
            state.angles.clear();
            state.spanInit = false;
        }
    }
}
