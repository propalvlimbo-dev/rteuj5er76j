package ru.elytrix.efc.checks.combat;

import java.util.Map;
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
 * Честный клиент всегда шлёт анимацию перед ударом.
 */
public final class KillAuraB extends Check {

    private final Map<UUID, Long> lastSwing = new ConcurrentHashMap<>();

    public KillAuraB(ElytrixFuckCheats plugin) {
        super(plugin, "KillAura", "B", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        lastSwing.remove(uuid);
    }

    @EventHandler
    public void onAnimation(PlayerAnimationEvent event) {
        lastSwing.put(event.getPlayer().getUniqueId(), System.currentTimeMillis());
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
        long now = System.currentTimeMillis();
        Long swing = lastSwing.get(attacker.getUniqueId());
        if (swing == null) {
            lastSwing.put(attacker.getUniqueId(), now);
            return;
        }
        // Окно 550 мс — как у NESS KillauraNoSwing (570 мс).
        if (now - swing > 550) {
            flag(plugin.getDataManager().get(attacker), "no-swing");
        }
    }
}
