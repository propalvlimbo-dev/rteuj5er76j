package ru.elytrix.efc.checks.combat;

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
import ru.elytrix.efc.util.CombatGeometry;
import ru.elytrix.efc.util.DamageUtil;

/**
 * Aim.C: удар мимо взгляда (порт Hawk EntityInteractDirection).
 * Луч из глаза должен пересекать хитбокс жертвы, иначе это доводка.
 * Как у Hawk проверяем ДВА луча: текущий и экстраполированный
 * (взгляд + последняя дельта) — удар в движении мимо не считается.
 * Расширение бокса растёт с пингом вместо лаг-компенсации Hawk.
 * Только игроки — по мобам нет точных боксов.
 */
public final class AimC extends Check {

    private static final class State {
        float lastDeltaYaw;
        float lastDeltaPitch;
        boolean has;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public AimC(ElytrixFuckCheats plugin) {
        super(plugin, "Aim", "C", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        State state = states.computeIfAbsent(event.getPlayer().getUniqueId(), key -> new State());
        state.lastDeltaYaw = wrap(event.getTo().getYaw() - event.getFrom().getYaw());
        state.lastDeltaPitch = event.getTo().getPitch() - event.getFrom().getPitch();
        state.has = true;
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
        if (CombatGeometry.eyeToBoxDistance(attacker, victim, 0.1) > 7.0) {
            return;
        }
        int ping = DamageUtil.pingOf(attacker) + DamageUtil.pingOf(victim);
        double expand = Math.min(cfg("base-expand", 0.3) + ping * cfg("per-ms", 0.004),
                cfg("cap-expand", 1.2));
        Location eye = attacker.getEyeLocation();
        boolean hit = CombatGeometry.rayHitsBoxDir(eye.toVector(), eye.getDirection(),
                victim, expand, 7.0);
        if (!hit) {
            State state = states.get(attacker.getUniqueId());
            if (state != null && state.has) {
                float yaw = eye.getYaw() + state.lastDeltaYaw;
                float pitch = Math.max(-90, Math.min(90, eye.getPitch() + state.lastDeltaPitch));
                hit = CombatGeometry.rayHitsBoxDir(eye.toVector(),
                        CombatGeometry.dirFromYawPitch(yaw, pitch), victim, expand, 7.0);
            }
        }
        if (!hit) {
            flag(plugin.getDataManager().get(attacker), "direction");
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
