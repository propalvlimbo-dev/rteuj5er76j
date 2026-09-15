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
 * Aim.F v2: роботизированный лок (идея Medusa AimAssistH).
 * v1 мерила «как близко прицел» — честный игрок в комбо тоже
 * близко, разделить нельзя: и легита цепляло, и ботов пропускало.
 * v2 мерит «как ровно держится»: у бота ошибка почти константа
 * (разброс &lt;3° при любом среднем до 8°), у человека рука гуляет —
 * микрокоррекции дают разброс 3–8° даже при точной наводке.
 * Окно оценивается, только если жертва стрейфится (угол на неё
 * проехал &gt;15° за окно): по идущему в лоб судить нельзя.
 * Флаг — 6 плохих окон подряд. Только в бою.
 */
public final class AimF extends Check {

    private static final int WINDOW = 20;
    private static final double MEAN_LIMIT = 8.0;
    private static final double STD_LIMIT = 3.0;
    private static final double TRAVEL_LIMIT = 15.0;
    private static final double BUFFER_LIMIT = 6.0;

    private static final class State {
        final List<Double> diffs = new ArrayList<>();
        double buffer;
        double lastMean;
        double lastStd;
        int invalid;
        int valid;
        UUID victim;
        long victimTime;
        double optTravel;
        float lastOpt;
        boolean hasOpt;
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
            state.optTravel = 0;
            state.hasOpt = false;
            return;
        }
        Player target = plugin.getServer().getPlayer(state.victim);
        if (target == null || !target.isOnline() || target.isDead()) {
            state.diffs.clear();
            state.optTravel = 0;
            state.hasOpt = false;
            return;
        }
        float deltaYaw = Math.abs(wrap(event.getTo().getYaw() - event.getFrom().getYaw()));
        if (deltaYaw > 0.3) {
            Location from = player.getLocation();
            long base = DamageUtil.rewindDelay(player, target);
            double diff = Double.MAX_VALUE;
            float optNow = 0;
            for (long shift : new long[] {50, 0, -50}) {
                Location to = plugin.getPositionHistory().locationAt(target, now - base + shift);
                float optimal = (float) Math.toDegrees(
                        Math.atan2(-(to.getX() - from.getX()), to.getZ() - from.getZ()));
                if (shift == 0) {
                    optNow = optimal;
                }
                float fixedRot = ((event.getTo().getYaw() % 360) + 360) % 360;
                float fixedOpt = ((optimal % 360) + 360) % 360;
                double point = Math.abs(fixedRot - fixedOpt);
                if (point > 180) {
                    point = 360 - point;
                }
                diff = Math.min(diff, point);
            }
            if (state.hasOpt) {
                state.optTravel += Math.abs(wrap(optNow - state.lastOpt));
            }
            state.lastOpt = optNow;
            state.hasOpt = true;
            state.diffs.add(diff);
        }
        if (state.diffs.size() >= WINDOW) {
            double travel = state.optTravel;
            state.optTravel = 0;
            state.hasOpt = false;
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
            if (travel < TRAVEL_LIMIT) {
                // Жертва не стрейфится — судить нечего, окно в утиль.
                state.valid++;
                state.buffer = Math.max(0, state.buffer - 0.5);
                return;
            }
            if (mean < MEAN_LIMIT && deviation < STD_LIMIT) {
                state.invalid++;
                state.buffer += 1;
                if (state.buffer > BUFFER_LIMIT) {
                    state.buffer = 0;
                    flag(plugin.getDataManager().get(player),
                            "lock mean=" + round1(mean) + " std=" + round1(deviation));
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
