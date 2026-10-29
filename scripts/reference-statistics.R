# Offline reference generator only. This never imports the Python implementation.
# Supply a separately installed, reviewed survival 3.8-6 reference library.
args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args) == 2L)
library(survival)
library(jsonlite)
stopifnot(getRversion() == "4.6.1",
          as.character(packageVersion("stats")) == "4.6.1",
          as.character(packageVersion("survival")) == "3.8.6",
          as.character(packageVersion("jsonlite")) == "2.0.0")
inputs <- fromJSON(args[1], simplifyVector=FALSE)
finite_or_null <- function(x) if (length(x) == 1L && is.finite(x)) unname(x) else NULL
observations <- function(rows) {
  if (!length(rows)) return(data.frame(time=numeric(), event=logical()))
  data.frame(time=vapply(rows,function(x) x[[1]],numeric(1)),
             event=vapply(rows,function(x) x[[2]],logical(1)))
}
km <- lapply(inputs$kaplan_meier, function(case) {
  data <- observations(case$observations)
  if (!nrow(data)) return(list(id=case$id,curve=list()))
  fit <- survfit(Surv(time,event)~1,data=data,conf.type="log-log",conf.int=.95,timefix=FALSE)
  summary <- summary(fit,censored=TRUE)
  curve <- lapply(seq_along(fit$time), function(i) list(
    time_months=fit$time[i],at_risk=fit$n.risk[i],events=fit$n.event[i],censored=fit$n.censor[i],
    survival=fit$surv[i],standard_error=finite_or_null(summary$std.err[i]),
    lower=finite_or_null(fit$lower[i]),upper=finite_or_null(fit$upper[i])))
  # Explicit earliest crossing convention, independent of R's plateau midpoint median.
  crossing <- which(fit$surv <= .5)
  list(id=case$id,curve=curve,median_survival_months=if(length(crossing)) fit$time[crossing[1]] else NULL)
})
logrank <- lapply(inputs$logrank, function(case) {
  left <- observations(case$left);right <- observations(case$right)
  left$group <- rep("left",nrow(left));right$group <- rep("right",nrow(right))
  data <- rbind(left,right)
  fit <- tryCatch(survdiff(Surv(time,event)~group,data=data,rho=0),error=function(e) {
    if(case$id %in% c("empty_group","no_events","all_fail_same_time")) return(NULL)
    stop(paste("Reference log-rank failed:",case$id,conditionMessage(e)))
  })
  statistic <- if(is.null(fit)) NULL else finite_or_null(fit$chisq)
  list(id=case$id,statistic=statistic,p_value=if(is.null(statistic)) NULL else pchisq(statistic,1,lower.tail=FALSE))
})
# Retain stats::fisher.test's equations; tighten its otherwise coarse root tolerance.
# The original locked stats namespace and function are not modified.
fisher_reference <- stats::fisher.test
root_environment <- new.env(parent=asNamespace("stats"))
root_environment$uniroot <- function(f,interval,...,tol=1e-12) stats::uniroot(f,interval,...,tol=tol)
environment(fisher_reference) <- root_environment
fisher <- lapply(inputs$fisher, function(case) {
  table <- matrix(unlist(case$table),nrow=2,byrow=TRUE)
  result <- fisher_reference(table,alternative="two.sided",conf.int=TRUE,conf.level=.95)
  list(id=case$id,p_value=result$p.value,conditional_odds_ratio=finite_or_null(result$estimate),
       conditional_odds_ratio_infinite=is.infinite(result$estimate),
       lower=finite_or_null(result$conf.int[1]),upper=finite_or_null(result$conf.int[2]),
       upper_unbounded=is.infinite(result$conf.int[2]))
})
mw <- lapply(inputs$expression, function(case) {
  left <- unlist(case$left);right <- unlist(case$right)
  result <- suppressWarnings(tryCatch(wilcox.test(left,right,alternative="two.sided",exact=FALSE,correct=TRUE),error=function(e) {
    if(case$id == "empty") return(NULL)
    stop(paste("Reference rank-test failed:",case$id,conditionMessage(e)))
  }))
  interval <- suppressWarnings(tryCatch(t.test(left,right,var.equal=FALSE,conf.level=.95),error=function(e) {
    if(case$id %in% c("empty","all_tied","one_patient")) return(NULL)
    stop(paste("Reference mean interval failed:",case$id,conditionMessage(e)))
  }))
  list(id=case$id,statistic=if(is.null(result)) NULL else finite_or_null(result$statistic),
       p_value=if(is.null(result)) NULL else finite_or_null(result$p.value),
       mean_difference=if(length(left)&&length(right)) mean(left)-mean(right) else NULL,
       mean_difference_lower=if(is.null(interval)) NULL else finite_or_null(interval$conf.int[1]),
       mean_difference_upper=if(is.null(interval)) NULL else finite_or_null(interval$conf.int[2]),
       degrees_of_freedom=if(is.null(interval)) NULL else finite_or_null(interval$parameter))
})
bh <- lapply(inputs$bh, function(case) {
  values <- vapply(case$p_values,function(x) if(is.null(x)) NA_real_ else x,numeric(1))
  adjusted <- p.adjust(values,method="BH",n=length(values))
  list(id=case$id,adjusted=lapply(adjusted,finite_or_null))
})
result <- list(schema_version=1,reference=list(r_version=R.version.string,
  stats_version=as.character(packageVersion("stats")),fisher_root_tolerance=1e-12,survival_version=as.character(packageVersion("survival")),
  jsonlite_version=as.character(packageVersion("jsonlite")),inputs_md5=unname(tools::md5sum(args[1])),
  generator_md5=unname(tools::md5sum(sub("--file=","",grep("^--file=",commandArgs(),value=TRUE))))),
  kaplan_meier=km,logrank=logrank,fisher=fisher,expression=mw,bh=bh)
write_json(result,args[2],auto_unbox=TRUE,pretty=TRUE,digits=16,na="null",null="null")
