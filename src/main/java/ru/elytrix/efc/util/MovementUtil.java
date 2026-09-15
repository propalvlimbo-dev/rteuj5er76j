package ru.elytrix.efc.util;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.block.Block;
import org.bukkit.entity.Player;
import org.bukkit.potion.PotionEffect;
import org.bukkit.potion.PotionEffectType;

/**
 * Общие помощники движения: состояния, где кинематика врёт,
 * блоки, эффекты и грейс после откидывания.
 * Exemptions движка (креатив, TP, вход, TPS) уже сидят в Check.flag —
 * здесь только то, чего там нет.
 */
public final class MovementUtil {

    private MovementUtil() {
    }

    private static final Map<UUID, Long> VELOCITY = new ConcurrentHashMap<>();

    public static void noteVelocity(UUID id) {
        if (id != null) {
            VELOCITY.put(id, System.currentTimeMillis());
        }
    }

    /** Откидывание меньше секунды назад — скорость и полёт честно врут. */
    public static boolean velocityRecent(UUID id) {
        Long t = VELOCITY.get(id);
        if (t == null) {
            return false;
        }
        if (System.currentTimeMillis() - t > 1000) {
            VELOCITY.remove(id);
            return false;
        }
        return true;
    }

    /**
     * Состояния, где проверять кинематику нельзя:
     * полёт, транспорт, элитры, трезубец.
     * При сомнениях — exempt, легит важнее детекта.
     */
    public static boolean cantCheck(Player player) {
        try {
            if (player.getAllowFlight()) {
                return true;
            }
            if (player.isInsideVehicle()) {
                return true;
            }
            if (player.isGliding()) {
                return true;
            }
            if (player.isRiptiding()) {
                return true;
            }
        } catch (Throwable ignored) {
            return true;
        }
        return false;
    }

    /** Уровень эффекта (amplifier) или -1, если эффекта нет. */
    public static int effectAmplifier(Player player, PotionEffectType type) {
        try {
            for (PotionEffect effect : player.getActivePotionEffects()) {
                if (effect != null && effect.getType() == type) {
                    return effect.getAmplifier();
                }
            }
        } catch (Throwable ignored) {
        }
        return -1;
    }

    public static Material feetType(Player player) {
        try {
            Block block = player.getLocation().getBlock();
            if (block != null) {
                return block.getType();
            }
        } catch (Throwable ignored) {
        }
        return Material.AIR;
    }

    public static Material belowType(Player player) {
        try {
            Location loc = player.getLocation();
            Location under = new Location(loc.getWorld(), loc.getX(), loc.getY() - 1.0, loc.getZ());
            Block block = under.getBlock();
            if (block != null) {
                return block.getType();
            }
        } catch (Throwable ignored) {
        }
        return Material.AIR;
    }

    public static boolean isClimbable(Material material) {
        return material == Material.LADDER
                || material == Material.VINE
                || material == Material.TWISTING_VINES
                || material == Material.WEEPING_VINES
                || material == Material.SCAFFOLDING;
    }

    public static boolean isLiquid(Material material) {
        return material == Material.WATER || material == Material.LAVA;
    }

    public static boolean isWeb(Material material) {
        return material == Material.COBWEB;
    }

    public static boolean isIce(Material material) {
        return material == Material.ICE
                || material == Material.PACKED_ICE
                || material == Material.BLUE_ICE;
    }

    /** Слизь и кровати гасят урон от падения — прыжок с них честный. */
    public static boolean isBounceSafe(Material material) {
        if (material == Material.SLIME_BLOCK) {
            return true;
        }
        try {
            return material != null && material.name().endsWith("_BED");
        } catch (Throwable ignored) {
            return false;
        }
    }

    /** Песок душ, почва душ и мёд ломают нормальную физику — пропускаем. */
    public static boolean isSlowGround(Material material) {
        return material == Material.SOUL_SAND
                || material == Material.SOUL_SOIL
                || material == Material.HONEY_BLOCK;
    }
}
