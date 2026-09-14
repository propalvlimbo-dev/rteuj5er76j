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
 * KillAura.B v2: удар без взмаха (silent-аура).
 * Окно 550 мс как у NESS. Умные гейты: разовый пропуск прощаем (лаг),
 * флаг только за 6 ударов подряд без взмаха у того, кто вообще машет.
 * Кто не махал ни разу, а сервер машет — сайлент после 10 ударов.
 * Если взмахов нет НИ У КОГО — событие сломано на форке, молчим.
 */
public final class KillAuraB extends Check {

    private final Map<UUID, Long> lastSwing = new ConcurrentHashMap<>();
    private final Map<UUID, Integer> grace = new ConcurrentHashMap<>();
    private final Map<UUID, Integer> streak = new ConcurrentHashMap<>();
    private final Set<UUID> swingers = ConcurrentHashMap.newKeySet();
    private boolean relaxedLogged;

    public KillAuraB(ElytrixFuckCheats plugin) {
        super(plugin, "KillAura", "B", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        lastSwing.remove(uuid);
        grace.remove(uuid);
        streak.remove(uuid);
        swingers.remove(uuid);
    }

    @EventHandler
    public void onAnimation(PlayerAnimationEvent event) {
        UUID uuid = event.getPlayer().getUniqueId();
        lastSwing.put(uuid, System.currentTimeMillis());
        swingers.add(uuid);
        grace.remove(uuid);
        streak.remove(uuid);
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
        }
        if (swingers.isEmpty()) {
            logRelaxed();
            return;
        }
        long now = System.currentTimeMillis();
        UUID uuid = attacker.getUniqueId();
        Long swing = lastSwing.get(uuid);
        if (swing != null && now - swing <= 550) {
            streak.remove(uuid);
            return;
        }
        if (!swingers.contains(uuid)) {
            int count = grace.merge(uuid, 1, Integer::sum);
            if (count >= 10) {
                flag(plugin.getDataManager().get(attacker), "no-swing silent");
            }
            return;
        }
        int count = streak.merge(uuid, 1, Integer::sum);
        if (count >= 6) {
            streak.remove(uuid);
            flag(plugin.getDataManager().get(attacker), "no-swing");
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
