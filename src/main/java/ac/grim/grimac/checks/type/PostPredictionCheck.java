package ac.grim.grimac.checks.type;

import ac.grim.grimac.utils.anticheat.update.PredictionComplete;

/**
 * EFC-совместимость: Grim PostPredictionCheck.
 */
public interface PostPredictionCheck extends PacketCheck {

    default void onPredictionComplete(final PredictionComplete predictionComplete) {
    }
}
