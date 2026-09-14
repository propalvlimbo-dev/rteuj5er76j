package ru.elytrix.efc.checks.combat;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.Location;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.DamageUtil;

/**
 * Aim.F: прилипание к цели (порт Medusa AimAssistH).
 * Разница между взглядом и идеальным доводом на жертву, 20 замеров:
 * у лока среднее &lt;7° и разброс &lt;12° окно за окном. Только в бою + VL.
 * Замер — минимум по 3 точкам пути жертвы (±50 мс от перемотки):
 * убирает ошибку перемотки, на которой джиттер-лок сидел ровно
 * на планке. Гейт 0.3° видит медленный лок, буфер +1/-0.5.
 */
public final class AimF extends Check {

    private static final class State {
        final List<Double> diffs = new ArrayList<>();
        double buffer;
        double lastMean;
        double lastStd;
        int invalid;
        int valid;
        UUID victim;
        long victimTime;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public AimF(ElytrixFuckCheats plugin) {
        super(plugin, "Aim", "F", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    /** Живые внутренности для /efc debug: последнее окно и счёт. */
    public String status(UUID uuid) {
        State state = states.get(uuid);
        if (state == null) {
            return "нет данных";
        }
        return "mean=" + round1(state.lastMean) + " std=" + round1(state.lastStd)
                + " buf=" + round1(state.buffer)
                + " inv=" + state.invalid + " val=" + state.valid;
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        State state = states.get(player.getUniqueId());
        if (state == null || state.victim == null) {
            return;
        }
        long now = System.currentTimeMillis();
        if (now - plugin.getDataManager().get(player).getLastAttack() > 3000
                || now - state.victimTime > 3000) {
            state.diffs.clear();
            return;
        }
        Player target = plugin.getServer().getPlayer(state.victim);
        if (target == null || !target.isOnline() || target.isDead()) {
            state.diffs.clear();
            return;
        }
        float deltaYaw = Math.abs(wrap(event.getTo().getYaw() - event.getFrom().getYaw()));
        if (deltaYaw > 0.3) {
            Location from = player.getLocation();
            long base = DamageUtil.rewindDelay(player, target);
            double diff = Double.MAX_VALUE;
            for (long shift : new long[] {50, 0, -50}) {
                Location to = plugin.getPositionHistory().locationAt(target, now - base + shift);
                float optimal = (float) Math.toDegrees(
                        Math.atan2(-(to.getX() - from.getX()), to.getZ() - from.getZ()));
                float fixedRot = ((event.getTo().getYaw() % 360) + 360) % 360;
                float fixedOpt = ((optimal % 360) + 360) % 360;
                double point = Math.abs(fixedRot - fixedOpt);
                if (point > 180) {
                    point = 360 - point;
                }
                diff = Math.min(diff, point);
            }
            state.diffs.add(diff);
        }
        if (state.diffs.size() >= 20) {
            double mean = 0;
            for (double diff : state.diffs) {
                mean += diff;
            }
            mean /= state.diffs.size();
            double variance = 0;
            for (double diff : state.diffs) {
                double d = diff - mean;
                variance += d * d;
            }
            variance /= state.diffs.size();
            double deviation = Math.sqrt(variance);
            state.diffs.clear();
            state.lastMean = mean;
            state.lastStd = deviation;
            if (mean < 7 && deviation < 12) {
                state.invalid++;
                state.buffer += 1;
                if (state.buffer > 6) {
                    state.buffer = 0;
                    flag(plugin.getDataManager().get(player), "glue");
                }
            } else {
                state.valid++;
                state.buffer = Math.max(0, state.buffer - 0.5);
            }
        }
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        Player attacker = DamageUtil.meleeAttacker(event);
        if (attacker == null) {
            return;
        }
        Entity victim = DamageUtil.entityOf(event);
        if (victim instanceof Player) {
            State state = states.computeIfAbsent(attacker.getUniqueId(), key -> new State());
            state.victim = victim.getUniqueId();
            state.victimTime = System.currentTimeMillis();
        }
    }

    private static double round1(double value) {
        return Math.round(value * 10) / 10.0;
    }

    private static float wrap(float delta) {
        double wrapped = delta % 360;
        if (wrapped > 180) {
            wrapped -= 360;
        } else if (wrapped < -180) {
            wrapped += 360;
        }
        return (float) wrapped;
    }
}
