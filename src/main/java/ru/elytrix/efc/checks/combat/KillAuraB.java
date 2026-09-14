package ru.elytrix.efc.checks.combat;

import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.player.PlayerAnimationEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.DamageUtil;

/**
 * KillAura.B: удар без взмаха рукой (silent / no-swing аура).
 * Окно 550 мс — как у NESS KillauraNoSwing (570 мс).
 * Самозащита от кривых форков: если взмахов нет НИ У КОГО на сервере —
 * значит событие сломано и проверка молча расслабляется (лог в консоль).
 * Если машет весь сервер, кроме одного — это сайлент, флаговать.
 */
public final class KillAuraB extends Check {

    private final Map<UUID, Long> lastSwing = new ConcurrentHashMap<>();
    private final Map<UUID, Integer> hitsWithoutSwing = new ConcurrentHashMap<>();
    private final Set<UUID> swingers = ConcurrentHashMap.newKeySet();
    private boolean relaxedLogged;

    public KillAuraB(ElytrixFuckCheats plugin) {
        super(plugin, "KillAura", "B", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        lastSwing.remove(uuid);
        hitsWithoutSwing.remove(uuid);
        swingers.remove(uuid);
    }

    @EventHandler
    public void onAnimation(PlayerAnimationEvent event) {
        UUID uuid = event.getPlayer().getUniqueId();
        lastSwing.put(uuid, System.currentTimeMillis());
        swingers.add(uuid);
        hitsWithoutSwing.remove(uuid);
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        Player attacker = DamageUtil.meleeAttacker(event);
        if (attacker == null) {
            return;
        }
        // Без getCause (кривые форки) шипы неотличимы от удара:
        // если жертва сама била меньше секунды назад — вероятно шипы.
        if (!DamageUtil.hasCause()) {
            Object rawVictim = DamageUtil.entityOf(event);
            if (rawVictim instanceof Player) {
                long victimAttack = plugin.getDataManager().get((Player) rawVictim).getLastAttack();
                if (System.currentTimeMillis() - victimAttack < 1000) {
                    return;
                }
            }
            // На таких форках дополнительно требуем: взмахи вообще должны
            // существовать на сервере, иначе событие тоже сломано.
            if (swingers.isEmpty()) {
                logRelaxed();
                return;
            }
        }
        long now = System.currentTimeMillis();
        UUID uuid = attacker.getUniqueId();
        Long swing = lastSwing.get(uuid);
        if (swing != null) {
            if (now - swing > 550) {
                flag(plugin.getDataManager().get(attacker), "no-swing");
            }
            return;
        }
        // Взмахов не было ни разу за сессию.
        int count = hitsWithoutSwing.merge(uuid, 1, Integer::sum);
        if (count < 10) {
            return;
        }
        if (!swingers.isEmpty()) {
            // Весь сервер машет, а этот — нет. Сайлент-аура.
            flag(plugin.getDataManager().get(attacker), "no-swing silent");
        } else {
            logRelaxed();
        }
    }

    private void logRelaxed() {
        if (!relaxedLogged) {
            relaxedLogged = true;
            plugin.getLogger().warning(
                    "KillAura.B relaxed: no swing packets server-wide, check will not flag.");
        }
    }
}
