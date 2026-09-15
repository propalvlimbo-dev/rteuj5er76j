package ac.grim.grimac.checks.type;

import ac.grim.grimac.utils.anticheat.update.BlockBreak;

/**
 * EFC-совместимость: Grim BlockBreakCheck.
 */
public interface BlockBreakCheck extends PostPredictionCheck {

    default void onBlockBreak(final BlockBreak blockBreak) {
    }

    default void onPostFlyingBlockBreak(final BlockBreak blockBreak) {
    }
}
