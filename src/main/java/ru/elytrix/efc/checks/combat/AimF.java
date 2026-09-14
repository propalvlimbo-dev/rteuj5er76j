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
 * Разница между взглядом и идеальным доводом на жертву, 25 замеров:
 * у лока среднее &lt;7° и разброс &lt;12° окно за окном, живая рука так
 * не держит — у неё флики и срывы. Только в бою + VL поверх.
 * Отличия от Medusa: гейт поворота 1.5° (smooth-lock крутится медленно),
 * буфер 10, разница yaw с коррекцией перехода через 0°/360°.
 */
public final class AimF extends Check {

    private static final class State {
        final List<Double> diffs = new ArrayList<>();
        int buffer;
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
        if (deltaYaw > 1.5) {
            Location from = player.getLocation();
            Location to = target.getLocation();
            float optimal = (float) Math.toDegrees(
                    Math.atan2(-(to.getX() - from.getX()), to.getZ() - from.getZ()));
            float fixedRot = ((event.getTo().getYaw() % 360) + 360) % 360;
            float fixedOpt = ((optimal % 360) + 360) % 360;
            double diff = Math.abs(fixedRot - fixedOpt);
            if (diff > 180) {
                diff = 360 - diff;
            }
            state.diffs.add(diff);
        }
        if (state.diffs.size() >= 25) {
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
            if (mean < 7 && deviation < 12) {
                if (++state.buffer > 10) {
                    state.buffer = 0;
                    flag(plugin.getDataManager().get(player), "glue");
                }
            } else if (state.buffer > 0) {
                state.buffer--;
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
