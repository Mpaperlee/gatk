/*
 * Copyright (c) 2010.
 *
 * Permission is hereby granted, free of charge, to any person
 * obtaining a copy of this software and associated documentation
 * files (the "Software"), to deal in the Software without
 * restriction, including without limitation the rights to use,
 * copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following
 * conditions:
 *
 * The above copyright notice and this permission notice shall be
 * included in all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
 * EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
 * OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
 * NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
 * HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
 * WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 * FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR
 * THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 */

package org.broadinstitute.sting.gatk.walkers.callset_assessment;

import org.broadinstitute.sting.commandline.ArgumentCollection;
import org.broadinstitute.sting.commandline.Input;
import org.broadinstitute.sting.commandline.Output;
import org.broadinstitute.sting.commandline.RodBinding;
import org.broadinstitute.sting.gatk.arguments.StandardVariantContextInputArgumentCollection;
import org.broadinstitute.sting.gatk.contexts.AlignmentContext;
import org.broadinstitute.sting.gatk.contexts.ReferenceContext;
import org.broadinstitute.sting.gatk.refdata.RefMetaDataTracker;
import org.broadinstitute.sting.gatk.walkers.RodWalker;
import org.broadinstitute.sting.utils.MathUtils;
import org.broadinstitute.sting.utils.variantcontext.Genotype;
import org.broadinstitute.sting.utils.variantcontext.GenotypeLikelihoods;
import org.broadinstitute.sting.utils.variantcontext.VariantContext;

import java.io.PrintStream;

/**
 * Assesses GLs at truth sites.
 * Use --variant and --truth
 */
public class AssessLikelihoodsAtTruth extends RodWalker<Integer, Integer> {

    @ArgumentCollection
    protected StandardVariantContextInputArgumentCollection variantCollection = new StandardVariantContextInputArgumentCollection();

    @Input(fullName="truth", shortName = "truth", doc="Input VCF truth file", required=true)
    public RodBinding<VariantContext> truthTrack;

    @Output
    PrintStream out;

    private int[] nonErrors = new int[101];
    private int[] observations = new int[101];

    public Integer map(RefMetaDataTracker tracker, ReferenceContext ref, AlignmentContext context) {
        if ( tracker == null ) // RodWalkers can make funky map calls
            return 0;

        VariantContext variant = tracker.getFirstValue(variantCollection.variants, context.getLocation());
        if ( variant == null )
            return 0;

        VariantContext truth = tracker.getFirstValue(truthTrack, context.getLocation());
        if ( truth == null )
            return 0;

        for ( final Genotype GLgenotype : variant.getGenotypes() ) {
            if ( GLgenotype.isNoCall() )
                continue;

            if ( !truth.hasGenotype(GLgenotype.getSampleName()) )
                continue;

            Genotype truthGenotype = truth.getGenotype(GLgenotype.getSampleName());
            if ( truthGenotype.isNoCall() )
                continue;

            GenotypeLikelihoods GLs = GLgenotype.getLikelihoods();
            if ( GLs == null ) {
                logger.warn("There are no GLs at " + context.getLocation());
                continue;
            }

            double[] normalizedGLs = MathUtils.normalizeFromLog10(GLs.getAsVector());
            double myGL = GLgenotype.isHomRef() ? normalizedGLs[0] : (GLgenotype.isHet() ? normalizedGLs[1] : normalizedGLs[2]);
            int roundedGL = (int)Math.round(100.0 * myGL);

            observations[roundedGL]++;
            boolean correctGenotype = GLgenotype.getType().equals(truthGenotype.getType());
            if ( correctGenotype )
                nonErrors[roundedGL]++;
        }

        return 1;
    }

    public Integer reduceInit() {
        return 0;
    }

    public Integer reduce(Integer counter, Integer sum) {
        return counter + sum;
    }

    public void onTraversalDone(Integer sum) {
        out.println("GL_probability\tone_minus_error_rate\tobservations");
        for (int i = 0; i < 101; i++) {
            if ( observations[i] > 0 )
                out.println(String.format("%.2f\t%.2f\t%d", (double)i/100.0, (double)nonErrors[i]/(double)observations[i], observations[i]));
        }
    }
}