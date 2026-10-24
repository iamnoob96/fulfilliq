# Offline optional analysis: no model fitting, network calls or warehouse mutations.
args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) stop("Usage: Rscript r_analysis/analyze.R INPUT_DIR OUTPUT_DIR")
inputs <- normalizePath(args[[1]], mustWork = TRUE)
output <- args[[2]]
local_lib <- "data/processed/R-library"
if (dir.exists(local_lib)) .libPaths(c(normalizePath(local_lib), .libPaths()))
required <- c("arules", "ggplot2", "jsonlite")
missing <- required[!vapply(required, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) stop(paste("Optional packages missing:", paste(missing, collapse=", "),
                               "See r_analysis/README.md; Python app works without these outputs."))
library(arules)
library(ggplot2)
dir.create(output, recursive = TRUE, showWarnings = FALSE)
unlink(file.path(output, "summary.json"))
manifest <- jsonlite::fromJSON(file.path(inputs, "manifest.json"))
file.copy(file.path(inputs, "manifest.json"), file.path(output, "input-manifest.json"), overwrite=TRUE)
baskets <- read.transactions(file.path(inputs, "transactions.csv"), format="basket", sep=",")
stopifnot(length(baskets) == manifest$transaction_count)
p <- manifest$parameters
rules <- apriori(baskets, parameter=list(support=p$min_support, confidence=p$min_confidence,
                                         minlen=2L, maxlen=p$max_length, target="rules"),
                 appearance=list(rhs="outcome=late", default="lhs"), control=list(verbose=FALSE))
rules <- rules[quality(rules)$lift >= p$min_lift]
lhs_items <- LIST(lhs(rules), decode=TRUE)
keep <- !vapply(lhs_items, function(x) any(startsWith(x, "outcome=")), logical(1))
rules <- rules[keep]
lhs_items <- LIST(lhs(rules), decode=TRUE)
result <- data.frame(antecedents=vapply(lhs_items, function(x) paste(sort(x), collapse="|"), character(1)),
                     consequents=rep("outcome=late", length(rules)), quality(rules), check.names=FALSE)
result <- result[order(-result$lift, -result$support, result$antecedents), ]
write.csv(result, file.path(output,"rules.csv"), row.names=FALSE)
logistics <- read.csv(file.path(inputs,"logistics.csv"))
regions <- read.csv(file.path(inputs,"regions.csv"))
sellers <- read.csv(file.path(inputs,"sellers.csv"))
write.csv(regions, file.path(output,"region-summary.csv"), row.names=FALSE)
base_theme <- theme_minimal(base_size=12)
save_plot <- function(plot, name) ggsave(file.path(output,name), plot + base_theme,
                                       width=10, height=5.5, dpi=130, bg="white")
save_plot(ggplot(logistics, aes(delivery_days)) + geom_histogram(binwidth=2, fill="#155e75") +
            labs(title="Historical delivery durations · valid delivered orders", x="Purchase to delivery (days)",
                 y="Orders"), "delivery-duration.png")
save_plot(ggplot(regions, aes(reorder(group,late_rate), late_rate)) + geom_col(fill="#155e75") +
            coord_flip() + labs(title="Historical late delivery rate by customer state", x="State",
                                 y="Late orders / eligible delivered orders"), "regional-delay.png")
save_plot(ggplot(logistics, aes(distance_km, delivery_days)) + geom_bin_2d(bins=50, na.rm=TRUE) +
            scale_fill_viridis_c(trans="log1p") + labs(title="Shipping distance and delivery duration · association only",
                x="Approximate ZIP-centroid distance (km)", y="Delivery duration (days)",fill="Orders"),
          "distance-duration.png")
save_plot(ggplot(sellers, aes(late_rate)) + geom_histogram(binwidth=.025, fill="#155e75", na.rm=TRUE) +
            labs(title="Seller late-rate distribution · multi-seller orders overlap",
                x="Historical late rate (includes small sellers)",y="Sellers"), "seller-performance.png")
session <- list(r_version=R.version.string,
                packages=as.list(setNames(vapply(required, function(x) as.character(packageVersion(x)), character(1)),required)),
                transaction_count=length(baskets), rules=length(rules),
                executed_at_utc=format(Sys.time(), tz="UTC", usetz=TRUE))
jsonlite::write_json(session,file.path(output,"r-session.json"),auto_unbox=TRUE,pretty=TRUE)
cat("R analysis finished. Run fulfilliq verify-r to compare Python/R and publish completed outputs.\n")
